from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, get_current_user_optional
from app.models.post import Post
from app.models.user import User
from app.models.author_subscription import AuthorSubscription
from app.schemas.post import PostCreate, PostUpdate, PostRead
from app.services.email import notify_new_post

router = APIRouter(prefix="/posts", tags=["posts"])


def get_post_or_404(post_id: int, db: Session) -> Post:
    post = db.get(Post, post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="글을 찾을 수 없음")
    return post


def subscribed_author_ids(user: User | None, db: Session) -> set[int]:
    # 이 사용자가 구독 중인 글쓴이 id들 (비로그인은 빈 집합)
    if user is None:
        return set()
    return set(
        db.scalars(
            select(AuthorSubscription.author_id).where(
                AuthorSubscription.subscriber_id == user.id
            )
        ).all()
    )


def can_view(post: Post, user: User | None, subs: set[int]) -> bool:
    # 공개글은 누구나. 비공개글은 작성자 본인 또는 그 작성자를 구독한 사람
    if post.visibility == "public":
        return True
    if user is None:
        return False
    return post.owner_id == user.id or post.owner_id in subs


@router.get("", response_model=list[PostRead])
def list_posts(
    db: Session = Depends(get_db), user: User | None = Depends(get_current_user_optional)
):
    # 공개글 + (로그인 시) 내 비공개글 + 내가 구독한 글쓴이의 비공개글
    if user is None:
        condition = Post.visibility == "public"
    else:
        allowed_authors = subscribed_author_ids(user, db) | {user.id}
        condition = or_(
            Post.visibility == "public", Post.owner_id.in_(allowed_authors)
        )
    return db.scalars(
        select(Post).where(condition).order_by(Post.created_at.desc())
    ).all()


@router.post("", response_model=PostRead, status_code=201)
def create_post(
    data: PostCreate,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),  # 로그인 필수
):
    post = Post(
        title=data.title,
        content=data.content,
        visibility=data.visibility,
        owner_id=user.id,  # 작성자 = 로그인 사용자
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    # 공개글만 구독자에게 알림 (비공개글은 알리지 않음)
    if post.visibility == "public":
        background.add_task(notify_new_post, post.id, post.title)
    return post


@router.get("/{post_id}", response_model=PostRead)
def get_post(
    post_id: int,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    post = get_post_or_404(post_id, db)
    # 볼 권한 없으면 존재 자체를 숨김(404)
    if not can_view(post, user, subscribed_author_ids(user, db)):
        raise HTTPException(status_code=404, detail="글을 찾을 수 없음")
    return post


@router.put("/{post_id}", response_model=PostRead)
def update_post(
    post_id: int,
    data: PostUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    post = get_post_or_404(post_id, db)
    if post.owner_id != user.id:
        raise HTTPException(status_code=403, detail="내 글만 수정할 수 있어")
    post.title = data.title
    post.content = data.content
    post.visibility = data.visibility
    db.commit()
    db.refresh(post)
    return post


@router.delete("/{post_id}", status_code=204)
def delete_post(
    post_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    post = get_post_or_404(post_id, db)
    if post.owner_id != user.id:
        raise HTTPException(status_code=403, detail="내 글만 삭제할 수 있어")
    db.delete(post)
    db.commit()
