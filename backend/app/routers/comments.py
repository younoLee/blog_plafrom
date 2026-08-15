import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, get_current_user_optional
from app.core.display import display_name_of
from app.core.ratelimit import limiter
from app.models.comment import Comment
from app.models.notification import Notification
from app.models.post import Post
from app.models.user import User
from app.routers.posts import can_view, get_post_or_404, subscribed_author_ids
from app.schemas.comment import CommentCreate, CommentRead
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


@router.get("", response_model=list[CommentRead])
def list_comments(
    post_id: int,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    _viewable_post_or_404(post_id, db, user)
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
    return rows


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
    db.commit()
    db.refresh(comment)

    # 글쓴이에게 알린다. **이게 없어서 익명 댓글이 열려 있는데도 글쓴이는 그 글에
    # 다시 들어가 눈으로 보기 전까지 몰랐다**(2026-08-14 격차검사 11번).
    #
    # 안 보내는 경우가 둘이다:
    #   - 주인 없는 글(owner_id NULL — 로그인 이전에 쓴 글) → 받을 사람이 없다
    #   - 글쓴이가 자기 글에 단 댓글 → 자기가 한 일을 자기에게 알리지 않는다
    if post.owner_id is not None and (user is None or user.id != post.owner_id):
        # 인앱 알림은 요청 트랜잭션에서 확실히 저장한다(새 글 알림과 같은 방침).
        db.add(
            Notification(user_id=post.owner_id, post_id=post_id, comment_id=comment.id)
        )
        db.commit()
        # 푸시는 백그라운드 — 발송이 느리거나 실패해도 댓글 작성 응답을 막지 않는다.
        # 이메일은 안 보낸다: 이 사이트의 발신 도메인이 없어 스팸함으로 가고(SES
        # 샌드박스), 익명 댓글마다 메일을 쏘면 도배 경로가 하나 더 생긴다.
        background.add_task(
            notify_new_comment_push, post_id, post.title, author, post.owner_id
        )
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
