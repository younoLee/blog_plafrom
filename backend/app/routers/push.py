from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.ratelimit import limiter
from app.core.textguard import has_nul
from app.models.push_subscription import PushSubscription
from app.models.user import User
from app.schemas.push import PushKey, PushStatus, PushSubscribe, PushUnsubscribe
from app.services.push import is_allowed_endpoint

router = APIRouter(prefix="/push", tags=["push"])


@router.get("/key", response_model=PushKey)
# 응답이 상수 하나라 비용은 거의 0이다. 그래도 거는 이유는 **계기판**이다 —
# 무인증 경로에 한도가 하나도 없으면 두드림이 로그에 남지 않는다.
@limiter.limit("120/minute")
def public_key(request: Request):
    """브라우저가 구독할 때 쓰는 VAPID 공개키.

    **비밀이 아니다** — 이 값으로 구독해야 우리 서버가 보낸 알림임을 브라우저가
    검증할 수 있으니 어차피 클라이언트에 나가야 한다. 로그인도 요구하지 않는다.

    키가 설정 안 됐으면 503. 프론트는 이걸 보고 '알림 켜기'를 아예 숨긴다 —
    누를 수 없는 버튼을 보여주는 것보다 없는 게 낫다."""
    if not settings.push_enabled:
        raise HTTPException(status_code=503, detail="푸시 알림이 설정돼 있지 않아")
    return PushKey(public_key=settings.vapid_public_key)


@router.get("", response_model=PushStatus)
def my_subscriptions(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    """이 계정이 몇 개 기기에서 알림을 받고 있는지.

    개수만 준다. endpoint는 사실상 기기 식별자라 돌려줄 이유가 없고, 화면에서
    필요한 건 '켜져 있나'와 '몇 대냐'뿐이다."""
    count = db.scalar(
        select(func.count())
        .select_from(PushSubscription)
        .where(PushSubscription.user_id == user.id)
    )
    return PushStatus(enabled=settings.push_enabled, devices=int(count or 0))


@router.post("", status_code=204)
@limiter.limit("30/hour")
def subscribe(
    request: Request,
    data: PushSubscribe,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """이 기기를 알림 수신 대상으로 등록한다.

    **같은 endpoint가 이미 있으면 주인만 갱신한다.** 브라우저는 재구독 시 같은
    endpoint를 돌려주는 경우가 많은데, 그때 행을 새로 만들면 같은 기기에 알림이
    두 번 간다. 그리고 공용 PC에서 A가 켜둔 뒤 B가 로그인해 켜면 endpoint는
    같으므로, 주인을 B로 옮겨야 A의 알림이 B 화면에 뜨지 않는다.

    키(p256dh·auth)도 함께 갱신한다 — 브라우저가 구독을 갱신하면서 키만 바꾸는
    경우가 있어서, endpoint만 보고 넘기면 이후 발송이 전부 복호화 실패한다."""
    if not settings.push_enabled:
        raise HTTPException(status_code=503, detail="푸시 알림이 설정돼 있지 않아")

    # 서버가 나중에 이 URL로 POST한다(services/push.py). 검사하지 않으면 내부 주소를
    # 등록해 우리 서버를 통해 VPC 안을 두드릴 수 있다 — 저장 전에 막는다.
    if not is_allowed_endpoint(data.endpoint):
        raise HTTPException(status_code=422, detail="지원하지 않는 푸시 서비스야")

    existing = db.scalar(
        select(PushSubscription).where(PushSubscription.endpoint == data.endpoint)
    )
    if existing is not None:
        # 남의 구독을 **endpoint만 알고** 가로채지 못하게 한다. 정당한 구독자는
        # 브라우저에서 endpoint·p256dh·auth를 함께 받으므로 셋을 다 갖고 있다.
        # 반대로 endpoint만 아는 사람(공유 화면·로그 유출 등)은 키를 모른다.
        # 키까지 일치할 때만 주인을 옮기면 공용 PC 시나리오는 그대로 통과하고
        # (같은 브라우저면 같은 구독 = 같은 키) 가로채기는 막힌다.
        if existing.user_id != user.id and (
            existing.p256dh != data.p256dh or existing.auth != data.auth
        ):
            raise HTTPException(
                status_code=409, detail="다른 계정이 등록한 기기야"
            )
        existing.user_id = user.id
        existing.p256dh = data.p256dh
        existing.auth = data.auth
    else:
        db.add(
            PushSubscription(
                user_id=user.id,
                endpoint=data.endpoint,
                p256dh=data.p256dh,
                auth=data.auth,
            )
        )
    db.commit()


# ── 해제 ────────────────────────────────────────────────────────────────────
#
# endpoint를 **URL이 아니라 본문**으로 받는다 (2026-09-02).
#
# 왜: Web Push endpoint는 그 브라우저·그 기기를 하나로 지목하는 식별자다
# (subscribe 주석이 "endpoint만 알면 남의 구독을 만질 수 있다"고 적어둔 것과 같은
# 성질이고, my_subscriptions가 개수만 돌려주는 이유도 이것이다). 쿼리스트링에 실으면
# uvicorn 액세스 로그와 중간 프록시(CloudFront) 로그에 원문이 그대로 남는다 —
# 응답 본문에서는 감추면서 요청 줄에는 매번 찍고 있었던 셈이다.
#
# **왜 POST 서브리소스인가**: 이 저장소는 같은 문제(초대 토큰을 URL에 싣지 않기)를
# auth.py의 preview_invite에서 이미 한 번 풀었고, 그때 고른 답이 "읽기인데 POST"였다
# (routers/auth.py:144-147). DELETE에 본문을 요구하는 쪽은 RFC 9110이 의미를 정의하지
# 않아 프록시·XHR 구현에 따라 본문이 조용히 버려질 수 있다. 같은 문제에는 같은 모양을
# 쓴다 — 저장소에 두 가지 관습이 생기면 다음 사람이 어느 쪽을 따를지 고민한다.


def _delete_subscriptions(db: Session, user: User, endpoint: str | None) -> None:
    """해제의 실제 동작. 신·구 두 경로가 **반드시 같은 판정**을 쓰게 한 몸통이다.

    **남의 구독은 못 지운다** — user_id 조건을 항상 함께 건다. endpoint만으로
    지우게 두면 남의 기기 endpoint를 아는 사람이 그 사람 알림을 꺼버릴 수 있다."""
    stmt = delete(PushSubscription).where(PushSubscription.user_id == user.id)
    # `if endpoint:`가 아니라 `is not None`이다. 빈 문자열(`?endpoint=`)은 falsy라
    # **그 기기만 끄려던 요청이 전 기기를 지운다.** 프론트는 이미 이 사고를 겪고
    # 우회 중이지만(api/push.ts에 "폰 알림까지 같이 꺼졌다"가 적혀 있다), 새 클라이언트를
    # 붙이는 사람은 독스트링만 보고 그대로 밟는다. (2026-08-11 교차검증)
    if endpoint is not None and endpoint != "":
        stmt = stmt.where(PushSubscription.endpoint == endpoint)
    db.execute(stmt)
    db.commit()


@router.post("/unsubscribe", status_code=204)
def unsubscribe(
    data: PushUnsubscribe,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """알림 끄기(현행 경로). endpoint를 본문에 주면 그 기기만, 없으면 전 기기."""
    _delete_subscriptions(db, user, data.endpoint)


@router.delete("", status_code=204, deprecated=True)
def unsubscribe_legacy(
    # max_length는 형제인 POST 본문(schemas/push.py의 endpoint)과 같은 값이다.
    # 거기엔 SafeModel + Field 상한이 이중으로 걸려 있었는데 여기만 맨몸이었다.
    endpoint: str | None = Query(default=None, max_length=2000),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """**구경로.** endpoint가 쿼리스트링에 실려 로그에 남는다. 위의 POST를 써라.

    **당장 없애지 않는 이유** (2026-09-02 판단): 프론트는 서비스워커가 붙은 앱이고
    (api/push.ts의 registration()), 이미 설치된 브라우저는 캐시된 옛 번들을 얼마간
    더 실행한다. 지금 지우면 그 기기들의 '알림 끄기'가 405가 되어 **끌 수가 없는**
    상태가 된다. 켤 수 없는 것보다 끌 수 없는 것이 나쁘다 — 개인정보를 줄이려던
    변경이 개인정보를 계속 받게 만드는 결과가 된다.

    남겨두는 동안에도 유출 자체는 줄지 않지만, 새 요청은 전부 POST로 가므로
    노출량은 캐시가 갈리는 속도만큼 0에 수렴한다. 프론트 배포가 한 바퀴 돈 뒤
    (액세스 로그에서 이 경로의 호출이 0이 된 것을 확인하고) 지운다."""
    # has_nul 호출처가 지금까지 무인증 입구 세 곳뿐이었다(posts.py·main.py·skin.py).
    # 인증이 필요한 이 라우트는 test_nul_guard.py의 목록 밖에 남아, NUL 한 글자로
    # psycopg2가 ValueError를 던지고 500 text/plain이 나갔다.
    if has_nul(endpoint):
        raise HTTPException(status_code=400, detail="endpoint에 허용되지 않는 문자가 있어")
    _delete_subscriptions(db, user, endpoint)
