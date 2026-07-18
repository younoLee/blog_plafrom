import re

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy import and_, func, or_, select, true
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user_optional, require_writer
from app.core.ratelimit import limiter
from app.models.author_subscription import AuthorSubscription
from app.models.post import Post
from app.models.user import User
from app.schemas.post import (
    PostCreate,
    PostList,
    PostMeta,
    PostRead,
    PostSummary,
    PostUpdate,
    PostVisibilityUpdate,
    SeriesItem,
    SeriesNav,
    TagCount,
)
from app.services.email import notify_new_post

# 연재 네비에 담을 최대 편수. 네비 목록이라 상한이 필요하다(제목만이라 가볍긴 하다).
SERIES_ITEMS_MAX = 100

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


def visible_condition(user: User | None, db: Session):
    """이 사용자에게 보이는 글의 SQL 조건. 목록·검색·메타가 모두 이걸 쓴다.

    목록/메타가 조건을 각자 만들면 한쪽만 고쳐져 비공개 글이 새기 쉽다(IDOR).
    """
    # 관리자는 전체
    if user is not None and user.role == "admin":
        return true()
    if user is None:
        return Post.visibility == "public"
    subs = subscribed_author_ids(user, db)
    return or_(
        Post.visibility == "public",
        Post.owner_id == user.id,  # 내 글은 공개범위 무관 전부
        # 구독자공개 글은 내가 그 작성자를 구독한 경우만 (private은 여기 안 걸림)
        and_(Post.visibility == "subscribers", Post.owner_id.in_(subs)),
    )


def _summary(p: Post) -> PostSummary:
    # 본문 전체 대신 발췌+읽기시간만 담아 응답 크기를 줄인다 (증폭 방지)
    return PostSummary(
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


def _like_escape(s: str) -> str:
    """ILIKE 패턴에 쓸 사용자 입력을 이스케이프.

    안 하면 q='%'가 전체 매칭이 되고, q='%%%%%'처럼 와일드카드만 잔뜩 보내면
    인덱스를 못 타 무거운 스캔이 된다. 역슬래시를 먼저 바꿔야 이중 이스케이프가 안 난다.
    """
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("", response_model=PostList)
# 무인증으로 부를 수 있고 검색은 일반 조회보다 비싸므로 상한을 둔다(넉넉해서 정상 열람엔 안 걸림).
@limiter.limit("60/minute")
def list_posts(
    request: Request,
    q: str | None = Query(None, min_length=2, max_length=100, description="제목·본문 검색어"),
    tag: str | None = None,
    limit: int = Query(10, ge=1, le=50),  # 상한 필수: ?limit=999999로 전체를 뽑아가는 걸 막는다
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    # 필터는 전부 공개범위 조건과 AND — 하나라도 OR로 새면 검색으로 비공개 글이 샌다(IDOR).
    filters = [visible_condition(user, db)]
    if tag:
        # 태그 필터: tags 배열에 이 태그가 포함된 글만 (Postgres 배열 contains)
        filters.append(Post.tags.contains([tag]))
    if q:
        # 한국어는 to_tsvector가 형태소를 몰라 풀텍스트가 안 먹는다 → pg_trgm + ILIKE.
        # 값은 파라미터로 바인딩되고(SQLi 없음) 메타문자는 위에서 이스케이프한다.
        pattern = f"%{_like_escape(q.strip())}%"
        filters.append(
            or_(
                Post.title.ilike(pattern, escape="\\"),
                Post.content.ilike(pattern, escape="\\"),
            )
        )

    # 페이지를 끊기 전 전체 개수(프론트의 '총 N개 / 다음 쪽' 표시용)
    total = db.scalar(select(func.count()).select_from(Post).where(*filters)) or 0
    posts = db.scalars(
        select(Post).where(*filters).order_by(Post.created_at.desc()).limit(limit).offset(offset)
    ).all()

    return PostList(
        items=[_summary(p) for p in posts],
        total=total,
        limit=limit,
        offset=offset,
    )


# 주의: 이 라우트는 반드시 "/{post_id}"보다 위에 있어야 한다.
# 아래에 두면 'meta'를 post_id(int)로 파싱하려다 422가 난다. (07-15 /subscribers/me와 같은 함정)
@router.get("/meta", response_model=PostMeta)
def posts_meta(
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    """사이드바용 집계 — 전체 글 수, 태그별 개수, 최근 글.

    목록이 페이지로 끊기면서 필요해졌다. 사이드바가 '현재 페이지'만 보고 집계하면
    2쪽에서 태그 목록이 그 페이지 글 기준으로 쪼그라든다.
    """
    condition = visible_condition(user, db)

    total = db.scalar(select(func.count()).select_from(Post).where(condition)) or 0

    # 태그별 글 수: 배열을 펼쳐(unnest) 태그 단위로 집계
    unnested = select(func.unnest(Post.tags).label("tag")).where(condition).subquery()
    tag_rows = db.execute(
        select(unnested.c.tag, func.count().label("cnt"))
        .group_by(unnested.c.tag)
        .order_by(func.count().desc(), unnested.c.tag)
        .limit(20)
    ).all()

    recent = db.scalars(
        select(Post).where(condition).order_by(Post.created_at.desc()).limit(5)
    ).all()

    return PostMeta(
        total=total,
        tags=[TagCount(tag=t, count=c) for t, c in tag_rows],
        recent=[_summary(p) for p in recent],
    )


@router.get("/{post_id}/series", response_model=SeriesNav | None)
def post_series(
    post_id: int,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    """이 글이 속한 연재의 목록·이전/다음. 연재가 아니면 null.

    목록은 '내가 볼 수 있는 글'만 담는다 — 안 그러면 남의 비공개 글 제목이 네비로 샌다.
    그래서 index/total도 '내 기준'이다(비공개가 섞인 연재면 남이 보는 번호와 다를 수 있음).
    """
    post = get_post_or_404(post_id, db)
    if not can_view(post, user, subscribed_author_ids(user, db)):
        raise HTTPException(status_code=404, detail="글을 찾을 수 없음")
    if not post.series:
        return None

    rows = db.scalars(
        select(Post)
        .where(visible_condition(user, db), Post.series == post.series)
        .order_by(Post.created_at)  # 연재는 쓴 순서대로 = 1편이 위
        .limit(SERIES_ITEMS_MAX)
    ).all()

    items = [SeriesItem(id=p.id, title=p.title, created_at=p.created_at) for p in rows]
    ids = [p.id for p in rows]
    # 이 글이 목록에 없을 수는 없다(위에서 can_view 통과 = visible_condition도 통과).
    pos = ids.index(post.id)
    return SeriesNav(
        series=post.series,
        total=len(items),
        index=pos + 1,
        items=items,
        prev=items[pos - 1] if pos > 0 else None,
        next=items[pos + 1] if pos + 1 < len(items) else None,
    )


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
        series=data.series,
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
    post.series = data.series
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
