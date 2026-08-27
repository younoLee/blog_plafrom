from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.display import display_name_of
from app.models.author_subscription import AuthorSubscription
from app.models.notification import Notification
from app.models.user import User

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


class SubscribeIn(BaseModel):
    author_id: int



@router.get("", response_model=list[int])
def my_subscriptions(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    # 내가 구독 중인 글쓴이 id 목록
    return list(
        db.scalars(
            select(AuthorSubscription.author_id).where(
                AuthorSubscription.subscriber_id == user.id
            )
        ).all()
    )


class SubscriptionOut(BaseModel):
    id: int
    name: str


class SubscriptionDetailOut(BaseModel):
    id: int
    name: str
    approved: bool  # 글쓴이가 이 구독을 승인했는지 (false=승인 대기)
    notify: bool  # 이 글쓴이의 새 글 이메일 알림을 켰는지


class NotifyIn(BaseModel):
    notify: bool


@router.get("/detail", response_model=list[SubscriptionDetailOut])
def my_subscriptions_detail(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    # 내가 구독(신청)한 글쓴이 (id + 이름 + 승인여부 + 알림여부) — 구독 관리 목록 표시용
    rows = db.execute(
        select(User.id, User.display_name, AuthorSubscription.approved, AuthorSubscription.notify)
        .join(AuthorSubscription, AuthorSubscription.author_id == User.id)
        .where(AuthorSubscription.subscriber_id == user.id)
        .order_by(User.id)
    ).all()
    # 표시명은 display_name에서만 온다 — 이메일 유도(email.split("@")[0])는
    # 2026-08-10 보안검사로 전부 걷어냈다. 여긴 인증 뒤라 위험도는 낮지만,
    # 유도가 한 군데라도 남으면 "이름은 이메일에서 만든다"는 관습이 살아남고
    # 그게 무인증 경로로 다시 새어나간 것이 이번 건이다. NULL이면 "회원".
    return [
        {
            "id": r.id,
            "name": display_name_of(r.id, r.display_name),
            "approved": r.approved,
            "notify": r.notify,
        }
        for r in rows
    ]


@router.put("/{author_id}/notify", response_model=SubscriptionDetailOut)
def set_notify(
    author_id: int,
    data: NotifyIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    sub = db.scalar(
        select(AuthorSubscription).where(
            AuthorSubscription.subscriber_id == user.id,
            AuthorSubscription.author_id == author_id,
        )
    )
    if sub is None:
        raise HTTPException(status_code=404, detail="먼저 구독해야 알림을 켤 수 있어")
    # 알림은 '승인된 다음에'만 켤 수 있다 (대기 중엔 열람 권한이 없으니 알림도 무의미)
    if not sub.approved:
        raise HTTPException(status_code=400, detail="아직 승인 대기중이라 알림을 켤 수 없어")
    sub.notify = data.notify
    db.commit()
    author = db.get(User, author_id)
    return {
        "id": author_id,
        # `author`가 None일 수 있다(mypy가 잡았다 — 2026-08-11 정적 분석).
        # FK가 ondelete=CASCADE라 글쓴이가 지워지면 이 구독 행도 같이 사라지지만,
        # **위에서 sub을 읽고 commit한 뒤**라 그 사이 삭제가 끼면 여기서 None이 되고
        # `.display_name`이 AttributeError → 500이다. 창은 좁아도 방어는 한 글자다.
        "name": display_name_of(author_id, author.display_name if author else None),
        "approved": sub.approved,
        "notify": sub.notify,
    }


@router.get("/authors", response_model=list[SubscriptionOut])
def subscribable_authors(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    # 구독할 수 있는 글쓴이(writer/admin) 목록 — 자기 자신은 제외
    rows = db.execute(
        select(User.id, User.display_name)
        .where(User.role.in_(("writer", "admin")), User.id != user.id)
        .order_by(User.id)
    ).all()
    return [{"id": r.id, "name": display_name_of(r.id, r.display_name)} for r in rows]


@router.post("", status_code=201)
def subscribe(data: SubscribeIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    # 구독 = '신청'. 글쓴이가 승인해야 approved=true가 되어 열람/알림 권한이 생긴다.
    if data.author_id == user.id:
        raise HTTPException(status_code=400, detail="자기 자신은 구독할 수 없어")
    if db.get(User, data.author_id) is None:
        raise HTTPException(status_code=404, detail="글쓴이를 찾을 수 없음")
    # 이미 신청/구독 중이면 그 상태를 그대로 반환(멱등)
    exists = db.scalar(
        select(AuthorSubscription).where(
            AuthorSubscription.subscriber_id == user.id,
            AuthorSubscription.author_id == data.author_id,
        )
    )
    if exists is None:
        db.add(AuthorSubscription(subscriber_id=user.id, author_id=data.author_id))  # approved=false(대기)
        # **글쓴이에게 알린다** (2026-08-27). 여기까지 오면 새 신청이라는 뜻이다.
        #
        # 이게 없어서 구독은 '신청 → 승인' 구조인데 신청이 온 사실이 글쓴이에게 아무
        # 신호도 안 갔다. 신청한 사람은 '승인 대기중'을 무기한 보고, 글쓴이는 모르니
        # 승인이 안 나고, 결과적으로 구독자공개 글이 영영 안 열렸다.
        #
        # 알림 자체를 못 만들던 이유는 notifications.post_id 가 NOT NULL 이었기
        # 때문이다. 구독 신청은 가리킬 글이 없다. f8a9b0c1d2e3 에서 풀었다.
        #
        # **같은 트랜잭션에 넣는다.** 아래 IntegrityError 로 롤백되면 알림도 같이
        # 사라져야 한다 — 신청이 안 만들어졌는데 "신청이 왔어"가 남으면 글쓴이는
        # 승인할 대상이 없는 알림을 보게 된다.
        db.add(Notification(user_id=data.author_id, actor_id=user.id))
        try:
            db.commit()
        except IntegrityError:  # 동시 중복 신청 레이스(유니크 충돌) — 500 대신 멱등으로 흡수
            db.rollback()
            exists = db.scalar(
                select(AuthorSubscription).where(
                    AuthorSubscription.subscriber_id == user.id,
                    AuthorSubscription.author_id == data.author_id,
                )
            )
            return {"approved": exists.approved if exists else False}
        return {"approved": False}
    return {"approved": exists.approved}


@router.delete("/{author_id}", status_code=204)
def unsubscribe(author_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    # 구독(또는 신청) 취소 = 관계 삭제
    sub = db.scalar(
        select(AuthorSubscription).where(
            AuthorSubscription.subscriber_id == user.id,
            AuthorSubscription.author_id == author_id,
        )
    )
    if sub is not None:
        db.delete(sub)
        db.commit()


# ── 글쓴이(author) 쪽: 나에게 온 구독 신청 관리 ──────────────────────────────
class RequestOut(BaseModel):
    id: int  # 신청한 사용자(subscriber) id
    name: str


@router.get("/requests", response_model=list[RequestOut])
def my_requests(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    # 나(글쓴이)에게 온 '승인 대기' 구독 신청 목록
    rows = db.execute(
        select(User.id, User.display_name)
        .join(AuthorSubscription, AuthorSubscription.subscriber_id == User.id)
        .where(
            AuthorSubscription.author_id == user.id,
            AuthorSubscription.approved.is_(False),
        )
        .order_by(AuthorSubscription.created_at)
    ).all()
    return [{"id": r.id, "name": display_name_of(r.id, r.display_name)} for r in rows]


def _subscription(db: Session, author_id: int, subscriber_id: int) -> AuthorSubscription | None:
    """이름이 `_pending_request`였는데 **pending을 안 걸렀다** — 승인된 구독도 그대로 준다.
    바로 위 `my_requests`는 `approved.is_(False)`를 명시하는데 여기만 빠져 있어서,
    읽는 사람은 "이 헬퍼와 두 라우트는 승인 대기만 다룬다"고 믿게 된다.
    실제로는 아래 DELETE가 **이미 승인된 구독자도 해지**한다(= 강제 해지).
    동작 자체는 글쓴이에게 필요한 기능이라 그대로 두고, **이름과 문서를 사실에 맞춘다.**
    (2026-08-11 교차검증 — 이름이 거짓말해서 재사용하면 승인 관계가 조용히 날아간다)
    """
    return db.scalar(
        select(AuthorSubscription).where(
            AuthorSubscription.author_id == author_id,
            AuthorSubscription.subscriber_id == subscriber_id,
        )
    )


@router.post("/requests/{subscriber_id}/approve", status_code=204)
def approve_request(
    subscriber_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    # 내 글에 대한 구독 신청 승인 (author = 나)
    sub = _subscription(db, user.id, subscriber_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="구독 신청을 찾을 수 없어")
    sub.approved = True
    db.commit()


@router.delete("/requests/{subscriber_id}", status_code=204)
def reject_request(
    subscriber_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    # 거절 = 그 구독 관계 삭제. 신청자는 다시 신청할 수 있다.
    # **승인된 구독자에게도 동작한다** = 강제 해지. 지우면 그 사람은 구독자공개 글을
    # 못 보고 알림도 끊긴다. 화면('받은 구독 신청')은 pending만 보여주므로 승인된 관계가
    # 여기로 오는 건 의도한 조작일 때뿐이다.
    sub = _subscription(db, user.id, subscriber_id)
    if sub is not None:
        db.delete(sub)
        db.commit()
