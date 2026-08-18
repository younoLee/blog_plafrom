import re

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy import and_, func, or_, select, true
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user_optional, require_writer
from app.core.ratelimit import limiter
from app.models.author_subscription import AuthorSubscription
from app.models.notification import Notification
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
from app.services.push import notify_new_post_push

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
    # 이 사용자가 '승인된' 구독을 가진 글쓴이 id들 (비로그인은 빈 집합).
    # 승인 대기(approved=false) 구독은 열람 권한을 주지 않는다.
    if user is None:
        return set()
    return set(
        db.scalars(
            select(AuthorSubscription.author_id).where(
                AuthorSubscription.subscriber_id == user.id,
                AuthorSubscription.approved.is_(True),
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
    # `q`엔 상한이 있는데 **바로 옆 `tag`엔 아무 제약이 없었다**(2026-08-12 동적 분석:
    # 6,000자 태그가 200으로 인덱스 조회까지 갔다). 고친 자리 옆의 안 쓸린 입구다.
    # 태그는 작성 시 스키마가 이미 짧게 제한하므로 조회 쪽도 같은 크기로 맞춘다.
    tag: str | None = Query(None, max_length=50),
    # 글쓴이로 거르기 — `/@handle` 화면이 쓴다. 값은 **핸들**이지 id가 아니다.
    # id를 받으면 화면이 주소(handle)를 id로 바꾸려고 조회를 한 번 더 해야 하고,
    # 그 조회가 실패하는 경우(없는 사람)를 두 곳에서 처리하게 된다.
    # 상한은 handle 컬럼과 같은 20자. 없는 핸들이면 빈 목록이다(404가 아니다 —
    # 목록은 '조건에 맞는 게 없다'를 표현할 수 있고, 화면이 그걸 이미 그린다).
    author: str | None = Query(None, max_length=20),
    limit: int = Query(10, ge=1, le=50),  # 상한 필수: ?limit=999999로 전체를 뽑아가는 걸 막는다
    # ⚠️ **`limit`엔 상한이 있는데 `offset`엔 없었다** — `q`↔`tag`와 글자 그대로 같은
    # "짝지어진 파라미터 중 한쪽만 안 쓸린" 모양이 여기 한 번 더 있었다(2026-08-12 검사).
    # `offset=2**63` → psycopg2가 `bigint out of range`로 던져 **무인증 500**이었다.
    # 임계값도 정확히 2^63으로 실측됐다(2^63-1은 200).
    offset: int = Query(0, ge=0, le=1_000_000),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    # **NUL 바이트를 먼저 막는다.** psycopg2는 `\x00`이 든 문자열을 만나면 DB에 닿기도 전에
    # `ValueError: A string literal cannot contain NUL characters`를 던지고, 핸들러가 없어
    # **인증 없이 500 + text/plain**이 나갔다(2026-08-12 동적 분석에서 `?tag=%00`·`?q=a%00b`로
    # 재현). `q=%00` 단독은 min_length=2에 걸리지만 `a%00b`는 길이 검사를 통과한다.
    # 프론트는 JSON을 기대하므로 text/plain 500은 파싱조차 못 한다 — 422로 정직하게 돌려준다.
    if (q and "\x00" in q) or (tag and "\x00" in tag):
        raise HTTPException(status_code=422, detail="검색어에 사용할 수 없는 문자가 있어.")

    # 필터는 전부 공개범위 조건과 AND — 하나라도 OR로 새면 검색으로 비공개 글이 샌다(IDOR).
    filters = [visible_condition(user, db)]
    if author:
        # 대소문자를 구분하지 않는다 — 주소는 그게 상식이고, 유니크 인덱스도
        # lower(handle)에 걸려 있어 두 값이 동시에 존재할 수 없다.
        filters.append(
            Post.owner_id.in_(
                select(User.id).where(func.lower(User.handle) == author.strip().lower())
            )
        )
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

    # 3컬럼만 고른다. 예전엔 `select(Post)`로 엔티티 전체를 읽었는데 쓰는 값은 아래 셋뿐이라,
    # 연재 전 편의 **본문(TEXT)이 통째로** Postgres→앱으로 흘렀다. 26편 기준 실측
    # **5.77ms → 0.40ms**(약 200KB 전송이 사라진다). 그리고 이건 글 상세를 열 때마다
    # 무조건 발생한다(프론트가 조건 없이 fetchSeries를 부른다). 상한이 100편이라
    # 연재가 차면 상세 1회당 약 800KB로 고정된다. — 2026-08-10 심층검사
    rows = db.execute(
        select(Post.id, Post.title, Post.created_at)
        .where(visible_condition(user, db), Post.series == post.series)
        .order_by(Post.created_at)  # 연재는 쓴 순서대로 = 1편이 위
        .limit(SERIES_ITEMS_MAX)
    ).all()

    items = [SeriesItem(id=p.id, title=p.title, created_at=p.created_at) for p in rows]
    ids = [p.id for p in rows]
    # 여기 있던 주석은 "이 글이 목록에 없을 수는 없다(can_view 통과 = visible_condition 통과)"였다.
    # **거짓이다** — 가시성만 보고 바로 위의 `.limit(SERIES_ITEMS_MAX)`를 안 봤다.
    # 정렬이 created_at 오름차순이라 101편째부터는 ids에 없고, `.index()`가 ValueError를 던진다.
    # main.py의 핸들러는 DB 계열만 잡으므로 그대로 **500 text/plain**이 나간다 —
    # 07-28·07-31·08-10에 세 번 없앤 그 모양이다. (2026-08-11 공백검사)
    #
    # 네비를 못 그리는 것과 글이 안 열리는 것 중에는 전자가 낫다. 상한 밖이면 None을 준다
    # (프론트는 fetchSeries가 null을 주는 경우를 이미 정상 처리한다 — SeriesBox를 안 그린다).
    if post.id not in ids:
        return None
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
    # 이 글쓴이를 구독+알림 켠 사람에게 알림 (공개·구독자공개 글. 비공개는 알리지 않음).
    # 구독자공개도 포함하는 이유: 구독자는 그 글을 볼 수 있으니 알림도 의미가 있다.
    if post.owner_id and post.visibility in ("public", "subscribers"):
        notify_uids = db.scalars(
            select(AuthorSubscription.subscriber_id).where(
                AuthorSubscription.author_id == post.owner_id,
                AuthorSubscription.approved.is_(True),
                AuthorSubscription.notify.is_(True),
            )
        ).all()
        # 인앱 알림(화면 종 배지용) — 요청 트랜잭션에서 확실히 저장
        for uid in notify_uids:
            db.add(Notification(user_id=uid, post_id=post.id))
        if notify_uids:
            db.commit()
        # 이메일 알림 — 실패해도 응답 막지 않게 백그라운드
        background.add_task(notify_new_post, post.id, post.title, post.owner_id)
        # 푸시 알림 — 같은 대상(위 notify_uids와 조건이 같다)에게 다른 채널로.
        # 메일과 **따로** 태스크를 거는 이유: 한쪽이 예외로 죽어도 다른 쪽은 나가야
        # 한다. 지금 이메일은 발신 도메인이 없어 스팸함에 꽂히므로, 실제로 닿는
        # 채널은 이쪽이다. 푸시 키가 없으면 함수 안에서 조용히 무동작.
        background.add_task(notify_new_post_push, post.id, post.title, post.owner_id)
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
