from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, get_current_user_optional
from app.core.ratelimit import limiter
from app.models.post import Post
from app.models.comment import Comment
from app.models.user import User
from app.routers.posts import can_view, subscribed_author_ids, get_post_or_404
from app.schemas.comment import CommentCreate, CommentRead

# 댓글은 글에 소속되므로 URL을 /posts/{post_id}/comments 로 둠
router = APIRouter(prefix="/posts/{post_id}/comments", tags=["comments"])


def _viewable_post_or_404(post_id: int, db: Session, user: User | None) -> Post:
    # 그 글을 볼 수 있는 사람만 댓글을 읽고/쓸 수 있음
    # (예전엔 존재 확인만 해서 비공개 글의 댓글이 누구에게나 노출됐음 — IDOR)
    post = get_post_or_404(post_id, db)
    if not can_view(post, user, subscribed_author_ids(user, db)):
        raise HTTPException(status_code=404, detail="글을 찾을 수 없음")
    return post


@router.get("", response_model=list[CommentRead])
def list_comments(
    post_id: int,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    _viewable_post_or_404(post_id, db, user)
    # 오래된 댓글이 위로 (대화 흐름 순서)
    return db.scalars(
        select(Comment).where(Comment.post_id == post_id).order_by(Comment.created_at)
    ).all()


@router.post("", response_model=CommentRead, status_code=201)
@limiter.limit("20/hour")  # 익명 댓글 도배(스팸) 방지 — IP당 시간당 20개
def create_comment(
    request: Request,
    post_id: int,
    data: CommentCreate,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    _viewable_post_or_404(post_id, db, user)
    comment = Comment(post_id=post_id, author=data.author, content=data.content)
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment


@router.delete("/{comment_id}", status_code=204)
def delete_comment(
    post_id: int,
    comment_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # 댓글 삭제(모더레이션): 글 작성자 본인 또는 관리자만
    post = get_post_or_404(post_id, db)
    comment = db.get(Comment, comment_id)
    if comment is None or comment.post_id != post_id:
        raise HTTPException(status_code=404, detail="댓글을 찾을 수 없음")
    if post.owner_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="댓글 삭제 권한이 없어")
    db.delete(comment)
    db.commit()
