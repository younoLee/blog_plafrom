from fastapi import APIRouter, Depends, HTTPException

from app.core.deps import require_writer
from app.models.user import User
from app.schemas.ai import DraftRequest, DraftResponse
from app.services.ai import generate_draft, AIKeyMissingError

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/draft", response_model=DraftResponse)
def create_draft(body: DraftRequest, user: User = Depends(require_writer)):
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
