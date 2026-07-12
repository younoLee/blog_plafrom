import re

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import select, or_, and_, true
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.ratelimit import limiter
from app.core.deps import get_current_user_optional, require_writer
from app.models.post import Post
from app.models.user import User
from app.models.author_subscription import AuthorSubscription
from app.schemas.post import PostCreate, PostUpdate, PostRead, PostSummary, PostVisibilityUpdate
from app.services.email import notify_new_post

router = APIRouter(prefix="/posts", tags=["posts"])


# --- 목록용 발췌/읽기시간 (본문 전체를 목록 응답에 싣지 않기 위해 서버에서 계산) ---
def _excerpt(md: str, max_len: int = 200) -> str:
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", md)  # 이미지 제거
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)  # 링크 → 표시 텍스트만
    t = re.sub(r"^#{1,6}\s+", "", t, flags=re.M)  # 헤딩 기호
    t = re.sub(r"^\s*[-*+]\s+", "", t, flags=re.M)  # 불릿
    t = re.sub(r"^\s*>\s?", "", t, flags=re.M)  # 인용
    t = re.sub(r"[*_~`]", "", t)  # 강조·코드 마커
    t = re.sub(r"\s+", " ", t).strip()
    return (t[:max_len].strip() + "…") if len(t) > max_len else t


def _reading_minutes(md: str) -> int:
    return max(1, round(len(md) / 500))  # 한글 기준 분당 약 500자


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
    # public: 누구나
    if post.visibility == "public":
        return True
    if user is None:
        return False
    # 관리자는 전부, 작성자 본인은 자기 글 전부(공개범위 무관)
    if user.role == "admin" or post.owner_id == user.id:
        return True
    # subscribers(구독자공개): 그 작성자를 구독한 사람만
    if post.visibility == "subscribers":
        return post.owner_id in subs
    # private(나만 보기): 위(본인/관리자) 외에는 불가
    return False


@router.get("", response_model=list[PostSummary])
def list_posts(
    tag: str | None = None,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    # 공개글 + (로그인 시) 내 글 전부 + 내가 구독한 글쓴이의 '구독자공개' 글
    # 관리자는 모든 글(조건 없음)
    if user is not None and user.role == "admin":
        condition = true()  # 전체 (항상 참)
    elif user is None:
        condition = Post.visibility == "public"
    else:
        subs = subscribed_author_ids(user, db)
        condition = or_(
            Post.visibility == "public",
            Post.owner_id == user.id,  # 내 글은 공개범위 무관 전부
            # 구독자공개 글은 내가 그 작성자를 구독한 경우만 (private은 여기 안 걸림)
            and_(Post.visibility == "subscribers", Post.owner_id.in_(subs)),
        )
    stmt = select(Post).where(condition)
    if tag:
        # 태그 필터: tags 배열에 이 태그가 포함된 글만 (Postgres 배열 contains)
        stmt = stmt.where(Post.tags.contains([tag]))
    posts = db.scalars(stmt.order_by(Post.created_at.desc())).all()
    # 본문 전체 대신 발췌+읽기시간만 담아 응답 크기를 줄인다 (증폭 방지)
    return [
        PostSummary(
            id=p.id,
            title=p.title,
            excerpt=_excerpt(p.content),
            reading_minutes=_reading_minutes(p.content),
            cover_image=p.cover_image,
            tags=p.tags,
            owner_id=p.owner_id,
            visibility=p.visibility,
            created_at=p.created_at,
            updated_at=p.updated_at,
        )
        for p in posts
    ]


@router.post("", response_model=PostRead, status_code=201)
@limiter.limit("30/hour")  # 글 도배·자동화 방지 (writer라도 시간당 30개 상한)
def create_post(
    request: Request,
    data: PostCreate,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(require_writer),  # 승인된 사람(writer/admin)만
):
    post = Post(
        title=data.title,
        content=data.content,
        cover_image=data.cover_image,
        tags=data.tags,
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
    user: User = Depends(require_writer),
):
    post = get_post_or_404(post_id, db)
    # 본인 글이거나 관리자면 수정 가능
    if post.owner_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="내 글만 수정할 수 있어")
    post.title = data.title
    post.content = data.content
    post.cover_image = data.cover_image
    post.tags = data.tags
    post.visibility = data.visibility
    db.commit()
    db.refresh(post)
    return post


@router.patch("/{post_id}/visibility", response_model=PostRead)
def change_visibility(
    post_id: int,
    data: PostVisibilityUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_writer),
):
    # 작성 후에도 공개범위만 빠르게 전환 (본인 글 또는 관리자)
    post = get_post_or_404(post_id, db)
    if post.owner_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="내 글만 공개범위를 바꿀 수 있어")
    post.visibility = data.visibility
    db.commit()
    db.refresh(post)
    return post


@router.delete("/{post_id}", status_code=204)
def delete_post(
    post_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_writer),
):
    post = get_post_or_404(post_id, db)
    # 본인 글이거나 관리자면 삭제 가능
    if post.owner_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="내 글만 삭제할 수 있어")
    db.delete(post)
    db.commit()
