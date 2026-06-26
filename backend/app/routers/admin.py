from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_admin
from app.models.user import User
from app.models.post import Post
from app.schemas.user import UserRead

# 관리자 전용 라우터 — 모든 엔드포인트가 require_admin 통과해야 함
router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/users", response_model=list[UserRead])
def list_users(db: Session = Depends(get_db)):
    # 이메일 인증을 마친 가입자만 목록에 (미인증=봇 가능성 → 제외해 목록 깨끗하게)
    return db.scalars(
        select(User).where(User.email_verified.is_(True)).order_by(User.id)
    ).all()


def _get_user_or_404(user_id: int, db: Session) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없음")
    return user


@router.post("/users/{user_id}/approve", response_model=UserRead)
def approve_user(user_id: int, db: Session = Depends(get_db)):
    # 승인: pending → writer (글쓰기 허용)
    user = _get_user_or_404(user_id, db)
    if user.role == "admin":
        raise HTTPException(status_code=400, detail="관리자 계정은 변경할 수 없어")
    user.role = "writer"
    db.commit()
    db.refresh(user)
    return user


@router.post("/users/{user_id}/revoke", response_model=UserRead)
def revoke_user(user_id: int, db: Session = Depends(get_db)):
    # 승인 취소: writer → pending (글쓰기 차단). 기존 글은 남지만 새 글/수정 불가
    user = _get_user_or_404(user_id, db)
    if user.role == "admin":
        raise HTTPException(status_code=400, detail="관리자 계정은 변경할 수 없어")
    user.role = "pending"
    db.commit()
    db.refresh(user)
    return user


@router.post("/users/{user_id}/ban", response_model=UserRead)
def ban_user(user_id: int, db: Session = Depends(get_db)):
    # 차단: role을 banned로. 로그인·토큰 모두 무효. 기존 글은 남음(admin이 따로 삭제 가능)
    user = _get_user_or_404(user_id, db)
    if user.role == "admin":
        raise HTTPException(status_code=400, detail="관리자 계정은 차단할 수 없어")
    user.role = "banned"
    user.token_version += 1  # 차단 즉시 기존 토큰 무효화
    db.commit()
    db.refresh(user)
    return user


@router.post("/users/{user_id}/unban", response_model=UserRead)
def unban_user(user_id: int, db: Session = Depends(get_db)):
    # 차단 해제: pending으로 되돌림(재승인 필요)
    user = _get_user_or_404(user_id, db)
    if user.role != "banned":
        raise HTTPException(status_code=400, detail="차단된 계정이 아니야")
    user.role = "pending"
    db.commit()
    db.refresh(user)
    return user


@router.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: int, db: Session = Depends(get_db)):
    # 영구 삭제(되돌리기 불가). admin은 삭제 불가
    user = _get_user_or_404(user_id, db)
    if user.role == "admin":
        raise HTTPException(status_code=400, detail="관리자 계정은 삭제할 수 없어")
    # 이 사용자의 글 삭제 → 댓글은 posts FK CASCADE로 함께 삭제
    db.execute(delete(Post).where(Post.owner_id == user_id))
    # author_subscriptions는 users FK ondelete CASCADE라 user 삭제 시 자동 정리
    db.delete(user)
    db.commit()
