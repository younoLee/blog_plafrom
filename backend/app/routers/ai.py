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
from app.services import ai_usage, llm_keys
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
    InvalidAPIKeyError,
    InvalidBaseURLError,
)

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


def _enforce_server_caps(db: Session, user_id: int) -> None:
    """서버키(Claude) 호출의 일일·월간 비용 캡. 초과 시 429. (BYOK는 본인 비용이라 제외)"""
    if ai_usage.count_today(db, user_id) >= settings.ai_daily_cap:
        raise HTTPException(
            status_code=429,
            detail=f"오늘 AI 초안 한도({settings.ai_daily_cap}회)를 다 썼어. 내일 다시 하거나 본인 키(BYOK)를 등록해줘",
        )
    if ai_usage.count_month(db, user_id) >= settings.ai_monthly_cap:
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
    if provider == "claude":
        _enforce_server_caps(db, user.id)

    user_key, base_url = (
        _load_byok_credential(db, user.id, provider)
        if provider in BYOK_PROVIDERS
        else (None, None)
    )

    try:
        markdown = generate_draft(body.memo, model, provider, user_key, base_url)
    except AIKeyMissingError:
        raise HTTPException(status_code=503, detail="AI 기능이 아직 설정되지 않았어 (서버 키 필요)")
    except Exception:
        raise HTTPException(status_code=502, detail="AI 초안 생성에 실패했어 (키/모델명 확인 후 다시 시도)")

    # 성공한 서버키 호출만 일일 카운트에 반영 (실패·BYOK는 안 셈)
    if provider == "claude":
        ai_usage.increment_today(db, user.id)
    return DraftResponse(markdown=markdown, model=model)
