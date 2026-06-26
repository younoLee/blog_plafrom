from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.deps import require_writer
from app.core.ratelimit import limiter
from app.models.user import User
from app.schemas.ai import DraftRequest, DraftResponse
from app.services.ai import generate_draft, AIKeyMissingError

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/draft", response_model=DraftResponse)
@limiter.limit("10/hour")  # AI 호출 비용 폭탄 방지 (승인된 writer라도 시간당 10회)
def create_draft(request: Request, body: DraftRequest, user: User = Depends(require_writer)):
    # 승인된 사람(writer/admin)만 — 아무나 호출해서 비용 나가는 걸 막음
    try:
        markdown = generate_draft(body.memo)
    except AIKeyMissingError:
        raise HTTPException(
            status_code=503,
            detail="AI 기능이 아직 설정되지 않았어 (서버에 ANTHROPIC_API_KEY 필요)",
        )
    except Exception:
        raise HTTPException(status_code=502, detail="AI 초안 생성에 실패했어 (잠시 후 다시 시도)")
    return DraftResponse(markdown=markdown)
