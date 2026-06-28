from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import require_writer
from app.core.ratelimit import limiter
from app.models.user import User
from app.schemas.ai import (
    DraftRequest,
    DraftResponse,
    AiModelInfo,
    AiModelsResponse,
    KeyStatus,
    KeysResponse,
    SetKeyRequest,
    UsageResponse,
)
from app.services.ai import (
    generate_draft,
    AIKeyMissingError,
    allowed_models_for,
    model_provider,
    DEFAULT_MODEL,
    MODELS,
)
from app.services import llm_keys, ai_usage
from app.services.llm_keys import (
    BYOK_PROVIDERS,
    NEEDS_BASE_URL,
    BYOKNotConfiguredError,
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
    # base_url은 서버가 직접 호출하는 주소 → SSRF 방지로 검증(내부/사설 주소 차단)
    if base_url:
        try:
            base_url = llm_keys.validate_base_url(base_url)
        except InvalidBaseURLError as e:
            raise HTTPException(status_code=400, detail=str(e))
    try:
        llm_keys.set_key(db, user.id, provider, body.key.strip(), base_url)
    except BYOKNotConfiguredError:
        raise HTTPException(status_code=503, detail="서버에 BYOK 암호화 키가 설정 안 됐어 (LLM_ENCRYPTION_KEY 필요)")
    return KeyStatus(provider=provider, has_key=True, base_url=base_url)


@router.delete("/keys/{provider}", response_model=KeyStatus)
def remove_key(provider: str, user: User = Depends(require_writer), db: Session = Depends(get_db)):
    if provider not in BYOK_PROVIDERS:
        raise HTTPException(status_code=400, detail="지원하지 않는 provider야")
    llm_keys.delete_key(db, user.id, provider)
    return KeyStatus(provider=provider, has_key=False)


@router.post("/draft", response_model=DraftResponse)
@limiter.limit("10/hour")  # AI 호출 비용 폭탄 방지 (승인된 writer라도 시간당 10회)
def create_draft(
    request: Request,
    body: DraftRequest,
    user: User = Depends(require_writer),
    db: Session = Depends(get_db),
):
    model = (body.model or DEFAULT_MODEL).strip()
    pk = llm_keys.providers_with_key(db, user.id)

    if model in MODELS:
        # 카탈로그 모델: Claude는 티어, BYOK는 키 등록 여부로 허용 결정
        if model not in allowed_models_for(user, pk):
            raise HTTPException(status_code=403, detail="이 모델을 쓸 권한이 없어 (결제 또는 키 등록 필요)")
        provider = model_provider(model)
    else:
        # 커스텀 모델(BYOK 전용): provider 명시 + 그 키 등록돼 있어야 함
        provider = (body.provider or "").strip()
        if provider not in BYOK_PROVIDERS:
            raise HTTPException(status_code=400, detail="커스텀 모델은 provider(openai/gemini)를 함께 보내야 해")
        if provider not in pk:
            raise HTTPException(status_code=400, detail=f"{provider} 키를 먼저 등록해줘 (설정)")

    # 서버키(Claude) 호출은 유저별 '일일 캡' + '월간 캡'으로 비용 폭주 방지 (BYOK는 본인 비용이라 제외)
    if provider == "claude":
        if ai_usage.count_today(db, user.id) >= settings.ai_daily_cap:
            raise HTTPException(
                status_code=429,
                detail=f"오늘 AI 초안 한도({settings.ai_daily_cap}회)를 다 썼어. 내일 다시 하거나 본인 키(BYOK)를 등록해줘",
            )
        if ai_usage.count_month(db, user.id) >= settings.ai_monthly_cap:
            raise HTTPException(
                status_code=429,
                detail=f"이번 달 AI 초안 한도({settings.ai_monthly_cap}회)를 다 썼어. 다음 달에 다시 하거나 본인 키(BYOK)를 등록해줘",
            )

    # BYOK provider는 사용자 키를 복호화해서 사용 (서버 claude만 서버 키)
    user_key = None
    base_url = None
    if provider in BYOK_PROVIDERS:
        try:
            cred = llm_keys.get_credential(db, user.id, provider)
        except BYOKNotConfiguredError:
            raise HTTPException(status_code=503, detail="서버에 BYOK 암호화 키가 설정 안 됐어")
        if cred is None:
            raise HTTPException(status_code=400, detail=f"{provider} 키를 먼저 등록해줘 (설정)")
        user_key, base_url = cred
        # SSRF 심층방어: 저장 후 DNS가 바뀌었을 수 있어(rebinding) 호출 직전 다시 검증
        if base_url:
            try:
                llm_keys.validate_base_url(base_url)
            except InvalidBaseURLError as e:
                raise HTTPException(status_code=400, detail=str(e))

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
