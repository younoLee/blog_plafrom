import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, get_current_user_optional
from app.core.display import display_name_of, site_owner
from app.core.ratelimit import limiter
from app.models.comment import Comment
from app.models.notification import Notification
from app.models.post import Post
from app.models.user import User
from app.routers.posts import can_view, get_post_or_404, subscribed_author_ids
from app.schemas.comment import CommentCreate, CommentRead, CommentUpdate
from app.services.push import notify_new_comment_push

logger = logging.getLogger(__name__)

# 한 글의 댓글 응답 상한. 페이지네이션 대신 안전 상한만 둔다 — 아래 조회부 주석 참고.
COMMENTS_MAX = 1000

# 댓글은 글에 소속되므로 URL을 /posts/{post_id}/comments 로 둠
router = APIRouter(prefix="/posts/{post_id}/comments", tags=["comments"])


def _viewable_post_or_404(post_id: int, db: Session, user: User | None) -> Post:
    # 그 글을 볼 수 있는 사람만 댓글을 읽고/쓸 수 있음
    # (예전엔 존재 확인만 해서 비공개 글의 댓글이 누구에게나 노출됐음 — IDOR)
    post = get_post_or_404(post_id, db)
    if not can_view(post, user, subscribed_author_ids(user, db)):
        raise HTTPException(status_code=404, detail="글을 찾을 수 없음")
    return post


def _site_owner_id(db: Session) -> int | None:
    """블로그 주인 = role이 admin인 사람 중 id가 가장 작은 사람.

    `/api/blog-owner`·`routers/skin.py`와 **같은 규칙**이다. 규칙이 갈라지면 어떤
    화면에서는 주인 배지가 붙고 어떤 화면에서는 안 붙는다.

    그 '같은 규칙'을 주석이 아니라 코드로 강제한다 — 2026-09-05까지 세 곳에 같은
    쿼리가 손으로 복사돼 있었다(09-04 검사 BQ-11).
    """
    owner = site_owner(db)
    return owner.id if owner else None


def _read(
    c: Comment, owner_id: int | None, post_owner_id: int, viewer_id: int | None = None
) -> CommentRead:
    """댓글 하나를 응답 모양으로. **배지는 id로만 판정한다**(이름은 안 본다).

    `viewer_id` 는 지금 이 응답을 받는 사람이다. `is_mine` 은 그 사람 자신에 대한
    1비트라 새로 새는 정보가 없다 — 화면이 '내 댓글'에 삭제·수정을 그릴 근거다.
    """
    return CommentRead(
        id=c.id,
        post_id=c.post_id,
        author=c.author,
        content=c.content,
        created_at=c.created_at,
        is_member=c.is_member,
        is_owner=c.user_id is not None and c.user_id == owner_id,
        is_author=c.user_id is not None and c.user_id == post_owner_id,
        is_mine=c.user_id is not None and viewer_id is not None and c.user_id == viewer_id,
    )


@router.get("", response_model=list[CommentRead])
# **이 저장소에서 무인증으로 가장 크게 부풀 수 있는 응답이다.** 바로 아래 상한 주석이
# 스스로 계산해뒀다 — 댓글 하나가 최대 2000자, 상한이 1000개라 한 요청이 약 10MB를
# 메모리에 만들어 내보내고, t2.micro(1GB)에서 그 GET이 동시 20개면 200MB다.
# 그런데 2026-08-27 훈련까지 **그 경로에 한도가 하나도 없었다** — 상한은 응답 크기를
# 묶었지만 '몇 번 부를 수 있나'는 아무도 안 묶고 있었다. 크기 상한과 호출 상한은 다른 방어다.
# 무인증 + DB 조회라 08-19 보안검사가 `/api/skin`·`/api/blog-owner`·`/api/authors/{h}`에
# 건 것과 같은 한도를 건다. 그때 셋만 쓸리고 이 자리는 남았다 — CloudFront의 `/api/*`는
# CachingDisabled라 엣지가 흡수하는 게 0이고 WAF에도 rate 룰이 없어서, 노트북 한 대로
# t2.micro 크레딧을 태울 수 있다(그때 44 req/s 실측). 120/분인 이유도 그때와 같다 —
# 낮게 걸면 정상 방문자가 먼저 걸린다(skin.py 주석).
@limiter.limit("120/minute")
def list_comments(
    request: Request,
    post_id: int,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    post = _viewable_post_or_404(post_id, db, user)
    # 오래된 댓글이 위로 (대화 흐름 순서)
    # 안전 상한. 이 저장소의 다른 목록은 전부 상한이 있는데(글 50 · 태그 20 · 최근글 5 ·
    # 연재 100 · 알림 20) 댓글만 빠져 있었다 — 2026-08-10 심층검사. 익명 작성이 열려 있고
    # (IP당 20/시간) 댓글 하나가 최대 2000자라, 한 글에 5,000개면 한 요청이 약 10MB를
    # 메모리에 만들어 내보낸다. t2.micro(1GB)에서 그 GET이 동시 20개면 200MB다.
    #
    # 상한에 **닿으면 로그를 남긴다.** 조용히 자르면 최신 댓글이 사라진 걸 아무도 모른다 —
    # 그게 이 저장소가 반복해서 당한 모양이라, 자르는 순간 시끄럽게 만든다.
    # 이 줄이 실제로 찍히면 그때는 페이지네이션을 붙일 때다(지금 댓글 수는 0이다).
    rows = db.scalars(
        select(Comment)
        .where(Comment.post_id == post_id)
        .order_by(Comment.created_at)
        .limit(COMMENTS_MAX)
    ).all()
    if len(rows) == COMMENTS_MAX:
        logger.warning(
            "글 %s의 댓글이 상한 %d에 닿았다 — 이후 댓글이 응답에서 잘리고 있다. 페이지네이션 필요.",
            post_id,
            COMMENTS_MAX,
        )
    owner_id = _site_owner_id(db)
    viewer_id = user.id if user else None
    return [_read(c, owner_id, post.owner_id if post.owner_id else -1, viewer_id) for c in rows]


@router.post("", response_model=CommentRead, status_code=201)
@limiter.limit("20/hour")  # 익명 댓글 도배(스팸) 방지 — IP당 시간당 20개
def create_comment(
    request: Request,
    post_id: int,
    data: CommentCreate,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    post = _viewable_post_or_404(post_id, db, user)
    # 로그인 사용자는 작성자명을 서버가 고정한다(자유 입력을 안 받는다).
    #
    # ⚠️ **이 고정만으로는 사칭이 안 막힌다.** 예전 주석은 여기에 "남의 이름 사칭 방지"라고
    # 적혀 있었지만 고정되는 건 로그인 쪽뿐이고, 익명은 같은 문자열을 그대로 칠 수 있다.
    # 2026-08-10에 무인증으로 재현했다:
    #   GET  /api/blog-owner          → 관리자 표시명 획득(무인증)
    #   POST /api/posts/{id}/comments {"author": "<그 이름>"} → 201
    #   GET  /api/posts/{id}/comments → 회원 댓글과 구분 불가
    #
    # **이름을 막는 쪽으로 고치지 말 것.** 동형문자(Cyrillic е)·제로폭 공백으로 우회되고,
    # 무엇보다 "그 이름은 계정이다"를 400으로 알려주게 되어 무인증 계정 열거 오라클이 된다
    # — 막으려던 것보다 나쁜 걸 만든다. 그래서 표시값은 그대로 두고 **계정을 따로 기록한다**
    # (user_id). 화면은 그걸 보고 회원 배지를 붙이므로 같은 이름을 쳐도 회원으로는 안 보인다.
    #
    # 그리고 표시명을 **이메일에서 유도하지 않는다** — 예전엔 email.split("@")[0]이었고,
    # 그 값이 공개 글의 댓글 목록으로 영구히 나갔다(같은 검사의 별건). display_name이
    # 없으면 "회원"으로 뭉갠다. 이름을 보이고 싶으면 create_user.py --display-name.
    author = display_name_of(user.id, user.display_name) if user is not None else data.author
    comment = Comment(
        post_id=post_id,
        user_id=user.id if user is not None else None,  # NULL = 익명
        author=author,
        content=data.content,
    )
    db.add(comment)
    # **댓글과 알림을 한 트랜잭션에 넣는다** (2026-09-04 검사 BE-4, 글 작성과 같은 고침).
    # 갈라 두면 알림 커밋이 실패했을 때 댓글은 저장됐는데 5xx 가 나가고, 익명 사용자가
    # 다시 누르면 같은 댓글이 둘이 된다 — 지울 수 있는 사람은 글쓴이·관리자뿐이다.
    db.flush()

    # 글쓴이에게 알린다. **이게 없어서 익명 댓글이 열려 있는데도 글쓴이는 그 글에
    # 다시 들어가 눈으로 보기 전까지 몰랐다**(2026-08-14 격차검사 11번).
    #
    # 안 보내는 경우가 둘이다:
    #   - 주인 없는 글(owner_id NULL — 로그인 이전에 쓴 글) → 받을 사람이 없다
    #   - 글쓴이가 자기 글에 단 댓글 → 자기가 한 일을 자기에게 알리지 않는다
    # '누구에게 알릴 것인가'를 값 하나로 들고 간다(None = 안 알린다). 커밋을 사이에 두고
    # 같은 판정을 두 번 쓰는데, bool 로 들면 아래에서 owner_id 가 다시 Optional 이 된다.
    notify_owner_id = (
        post.owner_id if post.owner_id is not None and (user is None or user.id != post.owner_id) else None
    )
    if notify_owner_id is not None:
        # 인앱 알림은 댓글과 **같은 커밋**에 실린다(새 글 알림과 같은 방침).
        db.add(
            Notification(user_id=notify_owner_id, post_id=post_id, comment_id=comment.id)
        )
    db.commit()
    db.refresh(comment)
    if notify_owner_id is not None:
        # 푸시는 백그라운드 — 발송이 느리거나 실패해도 댓글 작성 응답을 막지 않는다.
        # 이메일은 안 보낸다: 이 사이트의 발신 도메인이 없어 스팸함으로 가고(SES
        # 샌드박스), 익명 댓글마다 메일을 쏘면 도배 경로가 하나 더 생긴다.
        background.add_task(
            notify_new_comment_push, post_id, post.title, author, notify_owner_id
        )
    # post.owner_id는 NULL일 수 있다(로그인 이전에 쓴 글). 그땐 글쓴이 배지가 붙을
    # 사람이 없으므로 -1을 넘긴다 — 실제 id와 절대 안 맞는 값이다.
    # 방금 쓴 사람에게는 `is_mine` 이 참이어야 한다 — 아니면 새로고침 전까지 자기 댓글에
    # 지우기·고치기가 안 보인다(익명이면 user 가 None 이라 그대로 false 다).
    return _read(
        comment, _site_owner_id(db), post.owner_id if post.owner_id else -1, user.id if user else None
    )


@router.delete("/{comment_id}", status_code=204)
def delete_comment(
    post_id: int,
    comment_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """댓글 삭제 — 글 작성자·관리자(모더레이션) **또는 본인**.

    본인 삭제는 2026-09-05에 열었다(09-04 검사 GAP-5). 그전까지 회원이 자기 댓글의
    오타나 실수를 스스로 지울 방법이 없어서, 남의 블로그에 남긴 말을 그 글쓴이에게
    부탁해야 했다. 익명 댓글은 여전히 못 지운다 — 소유를 증명할 방법이 없고,
    IP 로 판정하면 같은 공유망의 남의 댓글을 지울 수 있게 된다.
    """
    post = get_post_or_404(post_id, db)
    comment = db.get(Comment, comment_id)
    if comment is None or comment.post_id != post_id:
        raise HTTPException(status_code=404, detail="댓글을 찾을 수 없음")
    mine = comment.user_id is not None and comment.user_id == user.id
    if not mine and post.owner_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="댓글 삭제 권한이 없어")
    db.delete(comment)
    db.commit()


@router.patch("/{comment_id}", response_model=CommentRead)
def update_comment(
    post_id: int,
    comment_id: int,
    data: CommentUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """댓글 수정 — **본인만, 내용만.**

    글쓴이·관리자에게는 열지 않는다. 삭제(모더레이션)와 수정은 다른 권한이다 —
    남의 말을 지우는 것은 '이 글에서 치운다'이지만 남의 말을 고치는 것은 **하지 않은
    말을 하게 만드는 것**이다. 익명 댓글도 못 고친다(소유를 증명할 방법이 없다).
    """
    post = get_post_or_404(post_id, db)
    comment = db.get(Comment, comment_id)
    if comment is None or comment.post_id != post_id:
        raise HTTPException(status_code=404, detail="댓글을 찾을 수 없음")
    if comment.user_id is None or comment.user_id != user.id:
        raise HTTPException(status_code=403, detail="내가 쓴 댓글만 고칠 수 있어")
    comment.content = data.content
    db.commit()
    db.refresh(comment)
    return _read(comment, _site_owner_id(db), post.owner_id if post.owner_id else -1, user.id)
