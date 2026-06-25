from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.post import Post
from app.models.comment import Comment
from app.schemas.comment import CommentCreate, CommentRead

# 댓글은 글에 소속되므로 URL을 /posts/{post_id}/comments 로 둠
router = APIRouter(prefix="/posts/{post_id}/comments", tags=["comments"])


def ensure_post_exists(post_id: int, db: Session) -> None:
    if db.get(Post, post_id) is None:
        raise HTTPException(status_code=404, detail="글을 찾을 수 없음")


@router.get("", response_model=list[CommentRead])
def list_comments(post_id: int, db: Session = Depends(get_db)):
    ensure_post_exists(post_id, db)
    # 오래된 댓글이 위로 (대화 흐름 순서)
    return db.scalars(
        select(Comment).where(Comment.post_id == post_id).order_by(Comment.created_at)
    ).all()


@router.post("", response_model=CommentRead, status_code=201)
def create_comment(post_id: int, data: CommentCreate, db: Session = Depends(get_db)):
    ensure_post_exists(post_id, db)
    comment = Comment(post_id=post_id, author=data.author, content=data.content)
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment
