import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import require_writer
from app.core.ratelimit import limiter
from app.models.user import User
from app.schemas.ai import (
    AiModelInfo,
    AiModelsResponse,
    DraftRequest,
    DraftResponse,
    KeysResponse,
    KeyStatus,
    SetKeyRequest,
    UsageResponse,
)
from app.services import ai_guard, ai_usage, llm_keys
from app.services.ai import (
    DEFAULT_MODEL,
    MODELS,
    AIKeyMissingError,
    allowed_models_for,
    generate_draft,
    model_provider,
)
from app.services.llm_keys import (
    BYOK_PROVIDERS,
    NEEDS_BASE_URL,
    BYOKNotConfiguredError,
    CredentialUndecryptableError,
    InvalidAPIKeyError,
    InvalidBaseURLError,
)

logger = logging.getLogger(__name__)


def _upstream_unreachable(e: BaseException) -> bool:
    """'업스트림에 못 닿았다' 계열인가 — 예외 원인 사슬까지 따라간다.

    타입만으로 못 가른다. 각 벤더 SDK(anthropic·openai·google·cohere)가 httpx 예외를
    자기 타입으로 감싸서 올리기 때문이다. 실제로 2026-07-28 카오스 훈련에서
    `except httpx.TimeoutException`만 걸어놨다가 **하나도 안 걸리는 걸** 재주입에서 발견했다
    (52초를 기다린 끝에 여전히 "키/모델명 확인"이 나왔다).

    그래서 __cause__/__context__ 사슬을 훑어 httpx의 연결·타임아웃 예외가 있는지 본다.
    벤더 SDK가 무엇으로 감싸든 밑바닥은 httpx다(넷 다 httpx를 쓴다).
    """
    seen = set()
    cur: BaseException | None = e
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if isinstance(cur, (httpx.TimeoutException, httpx.TransportError)):
            return True
        cur = cur.__cause__ or cur.__context__
    return False


router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/models", response_model=AiModelsResponse)
def list_models(user: User = Depends(require_writer), db: Session = Depends(get_db)):
    # Claude는 티어, OpenAI/Gemini는 그 사용자가 키를 등록했을 때만 노출
    pk = llm_keys.providers_with_key(db, user.id)
    allowed = allowed_models_for(user, pk)
    return AiModelsResponse(
        models=[AiModelInfo(id=m, label=MODELS[m][0], provider=MODELS[m][1]) for m in allowed],
        default=DEFAULT_MODEL,
    )


@router.get("/usage", response_model=UsageResponse)
def get_usage(user: User = Depends(require_writer), db: Session = Depends(get_db)):
    # 서버키(Claude) 호출의 오늘/이번 달 사용량 + 캡. 프론트가 '남은 횟수' 표시에 사용.
    return UsageResponse(
        daily_used=ai_usage.count_today(db, user.id),
        daily_cap=settings.ai_daily_cap,
        monthly_used=ai_usage.count_month(db, user.id),
        monthly_cap=settings.ai_monthly_cap,
    )


# --- BYOK 키 관리 (자기 키만, 값은 절대 안 내려줌) ---
@router.get("/keys", response_model=KeysResponse)
def list_keys(user: User = Depends(require_writer), db: Session = Depends(get_db)):
    pk = llm_keys.providers_with_key(db, user.id)
    return KeysResponse(
        keys=[
            KeyStatus(
                provider=p,
                has_key=p in pk,
                base_url=llm_keys.get_base_url(db, user.id, p) if p in pk else None,
            )
            for p in BYOK_PROVIDERS
        ]
    )


@router.put("/keys/{provider}", response_model=KeyStatus)
def set_key(
    provider: str,
    body: SetKeyRequest,
    user: User = Depends(require_writer),
    db: Session = Depends(get_db),
):
    if provider not in BYOK_PROVIDERS:
        raise HTTPException(status_code=400, detail="지원하지 않는 provider야")
    base_url = (body.base_url or "").strip() or None
    if provider in NEEDS_BASE_URL and not base_url:
        raise HTTPException(status_code=400, detail="이 provider는 주소(base URL)도 필요해 (예: https://api.x.ai/v1)")
    # 키 형식 검증 — 오타·엉뚱한 값이 암호화 저장까지 가지 않게 막음(provider별 접두사 + 공통 문자)
    try:
        clean_key = llm_keys.validate_api_key(provider, body.key)
    except InvalidAPIKeyError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # base_url은 서버가 직접 호출하는 주소 → SSRF 방지로 검증(내부/사설 주소 차단)
    if base_url:
        try:
            base_url = llm_keys.validate_base_url(base_url)
        except InvalidBaseURLError as e:
            raise HTTPException(status_code=400, detail=str(e))
    try:
        llm_keys.set_key(db, user.id, provider, clean_key, base_url)
    except BYOKNotConfiguredError:
        raise HTTPException(status_code=503, detail="서버에 BYOK 암호화 키가 설정 안 됐어 (LLM_ENCRYPTION_KEY 필요)")
    return KeyStatus(provider=provider, has_key=True, base_url=base_url)


@router.delete("/keys/{provider}", response_model=KeyStatus)
def remove_key(provider: str, user: User = Depends(require_writer), db: Session = Depends(get_db)):
    if provider not in BYOK_PROVIDERS:
        raise HTTPException(status_code=400, detail="지원하지 않는 provider야")
    llm_keys.delete_key(db, user.id, provider)
    return KeyStatus(provider=provider, has_key=False)


# create_draft의 세 갈래를 각자 이름 붙은 헬퍼로 분리한다(복잡도↓·경로별 테스트 용이).
# 1) 어떤 모델/provider를 쓸지 결정하며 권한을 검사, 2) 서버키 비용 캡, 3) BYOK 키 로드.


def _resolve_provider(body: DraftRequest, user: User, pk: set[str]) -> tuple[str, str]:
    """(model, provider) 결정 + 권한 검사. 카탈로그 모델은 티어/키로, 커스텀 모델은
    provider 명시+키 등록으로 허용을 판단한다. 위반 시 403/400."""
    model = (body.model or DEFAULT_MODEL).strip()
    if model in MODELS:
        if model not in allowed_models_for(user, pk):
            raise HTTPException(status_code=403, detail="이 모델을 쓸 권한이 없어 (결제 또는 키 등록 필요)")
        return model, model_provider(model)
    # 커스텀 모델(BYOK 전용): provider 명시 + 그 키 등록돼 있어야 함
    provider = (body.provider or "").strip()
    if provider not in BYOK_PROVIDERS:
        raise HTTPException(status_code=400, detail="커스텀 모델은 provider(openai/gemini)를 함께 보내야 해")
    if provider not in pk:
        raise HTTPException(status_code=400, detail=f"{provider} 키를 먼저 등록해줘 (설정)")
    return model, provider


def _reserve_abuse_slot(db: Session, user_id: int) -> None:
    """시간당 '시도' 캡 — provider 무관(BYOK 포함), 실패도 셈. 초과 시 429.

    **원자적 예약(reserve-then-check).** 예전엔 count_hour로 읽고 나중에 따로 증가했는데,
    그 사이 동시 요청들이 전부 같은 값을 읽어 캡을 넘겨 통과했다(TOCTOU) + 증가끼리 서로
    덮어써(lost update) 과소집계됐다. 이제 한 UPDATE로 올리고 그 반환값으로 판단하므로
    동시요청이 캡을 못 넘는다. **공유 데모 계정 비용 방어의 핵심** — 계정 기준이라 여러 IP로
    몰려도 시간당 총량이 하드 캡된다(slowapi 인메모리 IP캡은 그 위의 싼 1차 필터).
    초과분도 카운트에 남아 재시도가 공짜가 아니다(원래 의도)."""
    if ai_usage.increment_hour(db, user_id) > settings.ai_hourly_cap:
        raise HTTPException(
            status_code=429,
            detail=f"시간당 AI 초안 한도({settings.ai_hourly_cap}회)를 다 썼어. 잠시 후 다시 시도해줘",
        )


def _check_guard_lockout(db: Session, user_id: int) -> None:
    """가드 위반이 시간당 상한을 넘은 계정은 그 창 동안 막는다(429).

    한 방에 뚫리는 인젝션은 드물다. 실제 공격은 문구를 바꿔가며 반복하는 시행착오라,
    **그 반복을 끊는 게** 이 캡의 목적이다(작업 지시서 §8). 정상 사용자는 위반 카운트가
    평생 0이라 이 경로를 밟지 않는다.

    검사는 벤더 호출 '전에' 한다 — 위반이 쌓인 계정이 돈을 더 쓰게 두지 않는다.
    다만 시간당 '시도' 예약(_reserve_abuse_slot) 뒤에 온다: 막힌 시도도 시도로 세야
    무한히 두드리는 게 공짜가 안 된다.

    문구는 뭉뚱그린다. 몇 번 걸렸고 몇 번 남았는지 알려주면 공격자에겐 계기판이 된다.
    """
    if ai_usage.count_guard_violations(db, user_id) >= settings.ai_guard_violation_cap:
        raise HTTPException(
            status_code=429,
            detail="초안 생성이 잠시 제한됐어. 시간이 지난 뒤 다시 시도해줘.",
        )


def _reserve_server_slot(db: Session, user_id: int) -> None:
    """서버키(Claude) 호출의 일일·월간 비용 캡 — **원자적 예약**. 초과 시 되돌리고 429.
    (BYOK는 본인 비용이라 제외)

    예전엔 `count_today() >= cap`으로 읽고, 성공한 뒤에 따로 증가시켰다. 그 사이가
    비어 있어서 동시 요청이 전부 같은 값을 읽고 전부 통과했다 — **읽기와 증가 사이에
    LLM 호출이 들어 있어 창이 밀리초가 아니라 수 초였다.**
    2026-07-30 비용 가드레일 훈련에서 실측: 일일 캡 20의 19회를 쓴 상태에서 동시 요청 5개를
    던지니 남은 한도가 1회인데 **5건 전부 통과해 24/20**이 됐다(창 3.0초, 초과분 4건 실청구).
    시간당 캡(원자적)이 상한을 걸어주지만 그건 '시간당 캡만큼 넘칠 수 있다'는 뜻일 뿐이다.

    그래서 시간당 캡과 같은 reserve-then-check로 맞춘다: 먼저 원자적으로 +1 하고
    그 반환값으로 판단한다. 통과 못 하면 예약을 되돌린다(취소도 원자적).

    월간은 일별 기록의 합이라 위 +1이 월간 합도 같이 올린다. 경계에서 동시 요청이
    겹치면 서로의 증가까지 보고 **둘 다 거절**될 수 있다 — 비용 가드레일에서 그 방향의
    오차는 의도된 것이다(넘겨 통과시키는 것보다 낫다)."""
    if ai_usage.increment_today(db, user_id) > settings.ai_daily_cap:
        ai_usage.decrement_today(db, user_id)
        raise HTTPException(
            status_code=429,
            detail=f"오늘 AI 초안 한도({settings.ai_daily_cap}회)를 다 썼어. 내일 다시 하거나 본인 키(BYOK)를 등록해줘",
        )
    if ai_usage.count_month(db, user_id) > settings.ai_monthly_cap:
        ai_usage.decrement_today(db, user_id)
        raise HTTPException(
            status_code=429,
            detail=f"이번 달 AI 초안 한도({settings.ai_monthly_cap}회)를 다 썼어. 다음 달에 다시 하거나 본인 키(BYOK)를 등록해줘",
        )


def _load_byok_credential(db: Session, user_id: int, provider: str) -> tuple[str, str | None]:
    """BYOK 사용자 키를 복호화해 (키, base_url) 반환. 미설정 503, 미등록 400.
    base_url은 SSRF 심층방어로 호출 직전 재검증(저장 후 DNS rebinding 가능)."""
    try:
        cred = llm_keys.get_credential(db, user_id, provider)
    except BYOKNotConfiguredError:
        raise HTTPException(status_code=503, detail="서버에 BYOK 암호화 키가 설정 안 됐어")
    except CredentialUndecryptableError as e:
        # 서버의 암호화 키가 바뀌어 예전 암호문을 못 푼다. 사용자 잘못이 아니므로 5xx로
        # 답하되, **사용자가 할 수 있는 일**(키 재등록)을 알려준다. 잡지 않으면 여기서
        # 500 text/plain이 나가 프론트가 파싱조차 못 한다(2026-07-31 심층검사에서 실측).
        logger.warning("BYOK 자격증명 복호화 실패: %s", e)
        raise HTTPException(
            status_code=503,
            detail=f"저장된 {provider} 키를 복호화할 수 없어 (서버 암호화 키가 바뀜). 설정에서 키를 다시 등록해줘.",
        ) from e
    if cred is None:
        raise HTTPException(status_code=400, detail=f"{provider} 키를 먼저 등록해줘 (설정)")
    user_key, base_url = cred
    if base_url:
        try:
            llm_keys.validate_base_url(base_url)
        except InvalidBaseURLError as e:
            raise HTTPException(status_code=400, detail=str(e))
    return user_key, base_url


@router.post("/draft", response_model=DraftResponse)
@limiter.limit("10/hour")  # AI 호출 비용 폭탄 방지 (승인된 writer라도 시간당 10회)
def create_draft(
    request: Request,
    body: DraftRequest,
    user: User = Depends(require_writer),
    db: Session = Depends(get_db),
):
    pk = llm_keys.providers_with_key(db, user.id)
    model, provider = _resolve_provider(body, user, pk)

    # 남용 캡(시간당 시도)을 원자적으로 '예약' — provider 무관, 호출 '전에' 센다.
    # reserve-then-check라 동시요청이 캡을 넘겨 통과하지 못한다(공유 데모 계정 방어의 핵심).
    # 실패하는 호출(느린 BYOK 등)도 이미 차감돼 무한 재시도가 공짜가 아니다.
    _reserve_abuse_slot(db, user.id)
    # 가드를 반복해서 두드린 계정은 여기서 끊는다(벤더 호출 전 = 돈 쓰기 전).
    _check_guard_lockout(db, user.id)
    # 비용 슬롯도 호출 '전에' 예약한다. 예전엔 여기서 읽고 성공 뒤에 증가시켜서,
    # 그 사이(=LLM 호출 시간)에 들어온 동시 요청이 캡을 넘겨 통과했다.
    if provider == "claude":
        _reserve_server_slot(db, user.id)

    user_key, base_url = (
        _load_byok_credential(db, user.id, provider)
        if provider in BYOK_PROVIDERS
        else (None, None)
    )

    # 실패한 서버키 호출은 세지 않는다(기존 의도) → 예약을 되돌린다. 무한 재시도가
    # 공짜가 되는 건 시간당 '시도' 캡이 막는다(그건 실패도 센다).
    # 되돌리기는 finally에 둔다 — 실패 경로가 셋(503/503/502)이라 각 except에 흩어놓으면
    # 하나만 빠뜨려도 사용자가 쓰지도 않은 한도를 잃는다.
    charged = False
    try:
        markdown = generate_draft(body.memo, model, provider, user_key, base_url)
        charged = True
    except AIKeyMissingError:
        raise HTTPException(status_code=503, detail="AI 기능이 아직 설정되지 않았어 (서버 키 필요)")
    except ai_guard.GuardViolation as e:
        # 가드에 걸린 출력은 **절대 사용자에게 안 내려간다.** 원본을 보여주면 그게 곧
        # 프롬프트 유출이고, 어떤 가드에 걸렸는지 알려주면 공격자 피드백 루프가 된다
        # → 사유는 로그에만, 사용자에겐 뭉뚱그린 한 줄.
        #
        # 환불하지 않는다(charged=True). 벤더 호출은 **성공했고 토큰은 이미 태웠다.**
        # 여기서 일일 슬롯을 돌려주면 인젝션 시도만 비용이 0이 되어, 캡이 걸린 계정으로
        # 가드를 무한히 두드려볼 수 있게 된다 — 정확히 반대로 가야 하는 방향이다.
        charged = True
        violations = ai_usage.increment_guard_violation(db, user.id)
        logger.warning(
            "AI 가드 위반: reason=%s user=%s model=%s provider=%s memo=%s 누적=%d/%d",
            e.reason,
            user.id,
            model,
            provider,
            ai_guard.memo_fingerprint(body.memo),  # 원문 대신 지문만
            violations,
            settings.ai_guard_violation_cap,
        )
        raise HTTPException(
            status_code=422,
            detail="초안 생성에 실패했어. 메모를 조금 다르게 써서 다시 시도해줘.",
        ) from e
    except Exception as e:
        if _upstream_unreachable(e):
            # 업스트림에 못 닿거나 제때 답을 못 받은 것 — 사용자가 고칠 수 있는 게 없다.
            # 예전엔 이것도 "키/모델명 확인"으로 안내해서, 2026-07-28 카오스 훈련에서
            # Anthropic을 도달 불가로 만들었을 때 **엉뚱한 곳을 고치라고 시켰다**.
            logger.warning("AI 업스트림 도달 실패: %r", e)
            raise HTTPException(
                status_code=503,
                detail="AI 서비스에 일시적으로 연결할 수 없어. 잠시 후 다시 시도해줘.",
            ) from e
        # 여기 남는 건 대체로 '요청이 거부됐다' 쪽이다(잘못된 키, 없는 모델, 안전 거부 등).
        logger.warning("AI 초안 생성 실패: %r", e)
        raise HTTPException(status_code=502, detail="AI 초안 생성에 실패했어 (키/모델명 확인 후 다시 시도)")
    finally:
        if provider == "claude" and not charged:
            ai_usage.decrement_today(db, user.id)

    return DraftResponse(markdown=markdown, model=model)
