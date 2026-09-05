from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session, aliased

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import require_admin
from app.core.display import display_name_of
from app.core.security import hash_invite_token, new_invite_token
from app.models.ai_usage import AiGuardViolation, AiUsage
from app.models.invite import Invite
from app.models.post import Post
from app.models.user import BANNED_ROLE, User
from app.schemas.invite import InviteCreate, InviteCreated, InviteOut
from app.schemas.user import UserRead
from app.services.ai_usage import count_today_all_users, today, tokens_today_all_users
from app.services.infra import gather_infra
from app.services.push import last_delivery
from app.services.ses_status import recipient_status

# 관리자 전용 라우터 — 모든 엔드포인트가 require_admin 통과해야 함
router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/infra")
def infra_status(db: Session = Depends(get_db)):
    """서버(EC2)+DB 실측 지표 — 관리자 인프라 대시보드용. (라우터가 require_admin으로 보호)"""
    data = gather_infra()
    try:
        conns = db.execute(
            text("select count(*) from pg_stat_activity where datname = current_database()")
        ).scalar()
        maxc = int(db.execute(text("show max_connections")).scalar())
        data["db"] = {"connections": int(conns or 0), "max_connections": maxc}
    except Exception:
        data["db"] = {"connections": None, "max_connections": None}
    # 마지막 새 글·새 댓글 알림 발송의 결과 (services/push.py 의 _last_delivery 주석).
    # 여태 이 숫자는 로그에만 있었고, 로그는 대부분 꺼져 있는 EC2 안에 있었다.
    data["last_push"] = last_delivery()
    return data


@router.get("/ai-guard")
def ai_guard_summary(db: Session = Depends(get_db)):
    """AI 가드에 걸린 시도와, 그 때문에 자동 제한된 계정 — 관리자 화면용.

    **왜 화면에 내놓는가 (2026-08-27).** `ai_guard_violation` 테이블은 진작 있었고
    임계를 넘으면 `routers/ai.py:236` 이 429로 막는데, **그 사실이 화면에 한 줄도 없었다.**
    남는 것은 로그 한 줄뿐이라 "왜 초안 생성이 안 되냐"는 문의가 오면 psql 을 켜야
    알 수 있었다. 그리고 제한은 사용자에게 뭉뚱그려 안내되므로(그 함수 주석: 몇 번
    걸렸고 몇 번 남았는지 알려주면 공격자에겐 계기판이 된다) **관리자조차 못 보면
    아무도 못 본다.**

    지금 시간창(UTC 정시 내림)만 본다. 자동 제한이 그 창을 기준으로 걸리므로
    '지금 막혀 있는 사람'과 화면이 일치한다. 지난 기록을 쌓아 보여주려면 보존 기간을
    정해야 하는데, 그건 개인정보 성격이라 따로 판단할 일이다.
    """
    hour = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    rows = db.execute(
        # ⚠️ `count` 에 라벨을 붙인다. SQLAlchemy 의 Row 는 tuple 을 물려받아서
        #    `r.count` 가 **tuple.count 메서드**를 가리킨다 — 숫자가 아니라 함수다.
        #    이 파일이 위에서 User.id ↔ Notification.id 겹침에 대해 적어둔 것과 같은
        #    부류인데, 그쪽은 이름이 겹친 것이고 이쪽은 내장 메서드와 겹친 것이다.
        #    mypy 가 잡았다(pytest 는 못 잡는다 — 값이 함수여도 JSON 직렬화 전까지 안 터진다).
        select(
            AiGuardViolation.user_id,
            AiGuardViolation.count.label("hits"),
            User.email,
            User.display_name,
        )
        .join(User, User.id == AiGuardViolation.user_id)
        .where(AiGuardViolation.hour == hour)
        .order_by(AiGuardViolation.count.desc(), AiGuardViolation.user_id)
    ).all()
    cap = settings.ai_guard_violation_cap
    return {
        "hour": hour.isoformat(),
        "cap": cap,
        "items": [
            {
                "user_id": r.user_id,
                # 이메일이 아니라 표시명 규칙을 따른다 — 관리자 화면의 다른 목록과 같다
                # (그쪽 주석: "이메일은 안 보여준다").
                "name": display_name_of(r.user_id, r.display_name),
                "count": r.hits,
                # 지금 막혀 있는가. 임계와 개수를 둘 다 보내면 화면이 스스로 판정하게
                # 되는데, 그러면 백엔드가 임계를 바꿔도 화면이 옛 기준으로 그린다.
                "blocked": r.hits >= cap,
            }
            for r in rows
        ],
    }


@router.get("/ai-usage")
def ai_usage_summary(db: Session = Depends(get_db)):
    """AI 초안의 호출 수·토큰과 그 상한 — 관리자 화면용.

    **왜 화면에 내놓는가.** 토큰 컬럼은 2026-08-11에 만들었지만(e1f2a3b4c5d6) 그 값을
    **사람이 볼 수 있는 곳이 한 군데도 없었다.** 캡이 걸리면 429가 나가고 로그에 한 줄
    남을 뿐이라, '오늘 얼마나 썼나'는 psql을 켜야만 알 수 있었다. 그런데 Anthropic
    청구는 AWS 밖이라 watch.sh가 보는 AWS Budgets가 원리적으로 못 본다 — 즉 이 숫자를
    안 보면 다음 명세서까지 아무도 모른다.

    **비용(원/달러)으로 환산하지 않는다.** 모델별 단가를 코드에 박으면 단가가 바뀌는
    날부터 조용히 틀린 금액을 보여주는데, 틀린 금액은 없는 것보다 나쁘다(믿고 결정을
    내리게 된다). 여기서는 청구에 비례하는 **토큰 수**만 정직하게 보여준다.
    """
    day = today()
    # 오늘 — 캡과 같은 값을 본다(services/ai_usage.py가 캡 판정에 쓰는 그 쿼리들).
    calls_today = count_today_all_users(db)
    tokens_today = tokens_today_all_users(db)

    # 최근 14일 추이. 오늘 하루만 보면 '평소 대비 튀었는가'를 알 수 없다.
    since = day - timedelta(days=13)
    daily = db.execute(
        select(
            AiUsage.day,
            func.sum(AiUsage.count).label("calls"),
            func.sum(AiUsage.input_tokens).label("input_tokens"),
            func.sum(AiUsage.output_tokens).label("output_tokens"),
        )
        .where(AiUsage.day >= since)
        .group_by(AiUsage.day)
        .order_by(AiUsage.day)
    ).all()

    # 이번 달 상위 사용자. 계정이 몇 개 안 되지만, 한 계정이 전체를 먹고 있는지가
    # 캡을 어디에 걸지 정할 때 필요한 정보다. 이메일은 안 내보낸다(표시명 규칙).
    month_start = day.replace(day=1)
    top = db.execute(
        select(
            AiUsage.user_id,
            User.display_name,
            func.sum(AiUsage.count).label("calls"),
            func.sum(AiUsage.input_tokens + AiUsage.output_tokens).label("tokens"),
        )
        .join(User, User.id == AiUsage.user_id)
        .where(AiUsage.day >= month_start)
        .group_by(AiUsage.user_id, User.display_name)
        .order_by(func.sum(AiUsage.input_tokens + AiUsage.output_tokens).desc())
        .limit(10)
    ).all()

    return {
        "today": {
            "day": day,
            "calls": calls_today,
            "tokens": tokens_today,
            "calls_cap": settings.ai_daily_cap_global,
            "tokens_cap": settings.ai_daily_token_cap_global,
        },
        "daily": [
            {
                "day": r.day,
                "calls": int(r.calls or 0),
                "input_tokens": int(r.input_tokens or 0),
                "output_tokens": int(r.output_tokens or 0),
            }
            for r in daily
        ],
        "top_users_month": [
            {
                "user_id": r.user_id,
                "name": display_name_of(r.user_id, r.display_name),
                "calls": int(r.calls or 0),
                "tokens": int(r.tokens or 0),
            }
            for r in top
        ],
        # per-user 캡도 같이 준다 — 화면에서 '이 숫자가 무엇에 대비되는지' 없이는
        # 숫자만 봐서는 많은지 적은지 판단할 수 없다.
        "caps": {
            "per_user_hourly": settings.ai_hourly_cap,
            "per_user_daily": settings.ai_daily_cap,
            "per_user_monthly": settings.ai_monthly_cap,
        },
    }


@router.get("/users", response_model=list[UserRead])
def list_users(db: Session = Depends(get_db)):
    # 이메일 인증을 마친 가입자만 목록에 (미인증=봇 가능성 → 제외해 목록 깨끗하게)
    return db.scalars(
        select(User).where(User.email_verified.is_(True)).order_by(User.id)
    ).all()


def _get_user_or_404(user_id: int, db: Session) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없음")
    return user


def _reject_banned(user: User) -> None:
    """차단된 계정에는 역할·등급을 못 바꾼다 — 해제는 unban 한 곳으로만.

    **왜 (2026-09-04 검사 SEC-06)** — unban_user 는 `role != BANNED_ROLE` 을 400 으로
    막아 '차단 해제는 pending 으로 되돌려 재승인을 받는다'는 정책을 지키는데, 옆의
    approve/revoke/toggle-pro 는 대상이 banned 인지 안 보고 role 을 덮었다. banned 에
    approve 를 한 번 누르면 **재승인 단계를 건너뛰고 곧장 writer** 가 된다.
    이 저장소는 회수 판정을 전부 '읽는 쪽이 role 을 본다'로 모아뒀기 때문에
    (models/user.py · services/push.py · email.py) role 이 바뀌는 순간 블로그·알림·
    글쓰기가 한꺼번에 되살아난다 — 차단이 조용히 풀리는 것이다.
    """
    if user.role == BANNED_ROLE:
        raise HTTPException(status_code=400, detail="차단된 계정이야. 먼저 차단을 풀어줘")


@router.post("/users/{user_id}/approve", response_model=UserRead)
def approve_user(user_id: int, db: Session = Depends(get_db)):
    # 승인: pending → writer (글쓰기 허용)
    user = _get_user_or_404(user_id, db)
    if user.role == "admin":
        raise HTTPException(status_code=400, detail="관리자 계정은 변경할 수 없어")
    _reject_banned(user)
    user.role = "writer"
    db.commit()
    db.refresh(user)
    return user


@router.post("/users/{user_id}/revoke", response_model=UserRead)
def revoke_user(user_id: int, db: Session = Depends(get_db)):
    # 승인 취소: writer → pending (글쓰기 차단). 기존 글은 남지만 새 글/수정 불가
    user = _get_user_or_404(user_id, db)
    if user.role == "admin":
        raise HTTPException(status_code=400, detail="관리자 계정은 변경할 수 없어")
    _reject_banned(user)
    user.role = "pending"
    db.commit()
    db.refresh(user)
    return user


@router.post("/users/{user_id}/ban", response_model=UserRead)
def ban_user(user_id: int, db: Session = Depends(get_db)):
    # 차단: role을 banned로. 로그인·토큰 모두 무효. 기존 글은 남음(admin이 따로 삭제 가능)
    user = _get_user_or_404(user_id, db)
    if user.role == "admin":
        raise HTTPException(status_code=400, detail="관리자 계정은 차단할 수 없어")
    user.role = BANNED_ROLE
    user.token_version += 1  # 차단 즉시 기존 토큰 무효화

    # 구독·기기 등록은 **건드리지 않는다.** 발송을 막는 일은 수신자 조회가 한다
    # (services/push.py·email.py의 `User.role != BANNED_ROLE`).
    #
    # 한때 여기서 push_subscriptions를 지우고 notify를 False로 내렸다가 뺐다(2026-08-26).
    # 두 가지가 걸렸다:
    #   ① unban_user가 그걸 되돌리지 않는다. 차단이 풀린 사용자는 자기가 구독하던 모든
    #      글쓴이의 알림이 꺼진 채 복귀하고, 그 사실을 알려주는 곳도 없다.
    #   ② 애초에 이 저장소가 기각한 방식이다 — models/user.py의 PUBLIC_BLOG_ROLES 주석이
    #      "①은 상태를 두 군데 두는 것이라 새 회수 경로가 생길 때마다 같이 안 고치면
    #      또 어긋난다"며 '읽는 쪽이 역할을 본다'를 골랐다. 발송도 같은 판단이 맞다.
    #      회수 경로가 늘어도 조회 조건 하나만 참이면 되고, 되돌리면 알림도 같이 돌아온다.
    db.commit()
    db.refresh(user)
    return user


@router.post("/users/{user_id}/unban", response_model=UserRead)
def unban_user(user_id: int, db: Session = Depends(get_db)):
    # 차단 해제: pending으로 되돌림(재승인 필요)
    user = _get_user_or_404(user_id, db)
    if user.role != BANNED_ROLE:
        raise HTTPException(status_code=400, detail="차단된 계정이 아니야")
    user.role = "pending"
    db.commit()
    db.refresh(user)
    return user


@router.post("/users/{user_id}/toggle-pro", response_model=UserRead)
def toggle_pro(user_id: int, db: Session = Depends(get_db)):
    # 유료(pro) 토글: AI 초안에서 Opus 등 상위 모델 해금/회수.
    # 지금은 admin이 수동으로. 나중에 Stripe 결제가 이 플래그를 대신 켜줌(C단계).
    user = _get_user_or_404(user_id, db)
    _reject_banned(user)
    user.is_pro = not user.is_pro
    # 켤 땐 만료 없음(None). 안 그러면 과거 결제의 pro_until이 남아 있어 다음 요청에서
    # _expire_pro_if_due(deps.py)가 즉시 되돌린다 → 관리자 수동 부여가 조용히 무효화됐다.
    if user.is_pro:
        user.pro_until = None
    db.commit()
    db.refresh(user)
    return user


@router.post("/users/{user_id}/release-handle", response_model=UserRead)
def release_handle(user_id: int, db: Session = Depends(get_db)):
    """이 계정이 잡고 있는 블로그 주소(`/@handle`)를 비운다.

    **왜 관리자 쪽에 있나 (2026-09-04 검사 SEC-04)** — `PATCH /auth/me/handle` 의 주석은
    '차단된 사람도 자기 주소를 지울 수 있다'고 적어뒀지만 사실이 아니었다. ban 이
    token_version 을 올려 토큰을 죽이고 get_current_user 가 banned 를 403 으로 끊으므로,
    차단된 계정에는 그 문을 열어줄 방법 자체가 없다(부를 주체가 없다).
    그런데 handle 은 유니크라(uq_users_handle_lower) 그 주소는 **계정을 지우기 전까지
    영구히 예약된 채** 남고, 다른 사람이 같은 주소를 쓰려 하면 409 를 받는다.
    해소 경로가 '계정 삭제' 하나뿐이었다 — 주소 하나 때문에 글까지 지우게 되는 셈이다.

    차단된 계정에만 열지 않는다. 오타·분쟁으로 주소를 회수해야 하는 경우는 상태와
    무관하게 생기고, 이건 관리자 전용 라우터다(prefix 의존성이 require_admin).
    """
    user = _get_user_or_404(user_id, db)
    if user.handle is None:
        raise HTTPException(status_code=400, detail="이 계정은 블로그 주소가 없어")
    user.handle = None
    db.commit()
    db.refresh(user)
    return user


@router.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: int, db: Session = Depends(get_db)):
    # 영구 삭제(되돌리기 불가). admin은 삭제 불가
    user = _get_user_or_404(user_id, db)
    if user.role == "admin":
        raise HTTPException(status_code=400, detail="관리자 계정은 삭제할 수 없어")
    # 이 사용자의 글 삭제 → 댓글은 posts FK CASCADE로 함께 삭제
    # (2026-08-15부터 posts.owner_id도 ondelete=CASCADE라 이 줄이 없어도 지워진다.
    #  그래도 남긴다 — '사용자 삭제가 글을 지운다'는 건 부수효과가 아니라 이 함수의
    #  의도이고, 코드에 안 적혀 있으면 다음 사람이 FK를 보고서야 알게 된다.)
    db.execute(delete(Post).where(Post.owner_id == user_id))
    # author_subscriptions·push_subscriptions 둘 다 users FK ondelete CASCADE라
    # user 삭제 시 자동 정리된다(models/author_subscription.py:17,20, push_subscription.py:38).
    db.delete(user)
    db.commit()


# ── 초대 (초대제 가입의 실제 절차) ──────────────────────────────────────────
#
# 여기가 '초대제'라는 말에 실체를 주는 곳이다. 그전까지 초대제는 register가
# 403을 주는 것뿐이었고, 계정은 DB를 직접 만져 만들었다 — 문서에 적힌 절차가
# 코드에 없었다.


@router.get("/invites", response_model=list[InviteOut])
def list_invites(db: Session = Depends(get_db)):
    """발급한 초대 전체(미사용·사용됨·만료 포함). 최신순.

    사용·만료된 것도 지우지 않고 보여준다 — '누구를 언제 들였나'가 초대제에서는
    감사 기록이다. 지워버리면 그 답을 영영 못 한다.

    그 기록을 **여기서 실제로 보여준다.** 처음엔 created_by_id·used_by_id를
    쓰기만 하고 화면엔 안 냈는데, 그러면 위 문장이 근거로 삼는 답을 psql로만
    볼 수 있다 — 남기는 이유가 절반만 성립한다.

    사용자 이름을 붙이는 데 relationship을 쓰지 않고 조인한다. 이 저장소의
    모델에는 relationship이 하나도 없고(전부 FK 컬럼 + 라우터에서 명시적 조인),
    lazy 로딩을 켜면 미리보기 같은 다른 Invite 조회에도 조인이 따라붙는다.
    발급자·가입계정이 지워졌으면 FK가 SET NULL이므로 outerjoin이라야 그 줄이
    목록에서 통째로 사라지지 않는다."""
    creator = aliased(User)
    redeemer = aliased(User)
    rows = db.execute(
        select(Invite, creator.email, redeemer.email)
        .outerjoin(creator, creator.id == Invite.created_by_id)
        .outerjoin(redeemer, redeemer.id == Invite.used_by_id)
        .order_by(Invite.id.desc())
    ).all()
    return [
        InviteOut.model_validate(invite).model_copy(
            update={"created_by_email": by, "used_by_email": used}
        )
        for invite, by, used in rows
    ]


@router.post("/invites", response_model=InviteCreated, status_code=201)
def create_invite(
    data: InviteCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """초대 발급. **원문 토큰이 나가는 건 이 응답 하나뿐이다.**

    DB에는 해시만 남으므로 링크를 다시 볼 방법이 없다. 놓쳤으면 취소하고 다시
    발급한다 — 재확인 기능을 만들면 해시로 저장한 의미가 사라진다.

    링크는 메일로 보내지 않는다. SES 샌드박스가 미검증 주소로의 발송을 막기
    때문이기도 하지만, 그게 아니어도 손으로 건네는 편이 낫다: 초대 사실을
    미리 알린 사람에게만 링크가 가고, 받는 쪽이 예고 없는 메일을 피싱으로
    의심할 일도 없다."""
    email = data.email.lower()
    # 이미 계정이 있으면 초대가 의미 없다. 관리자는 가입자 목록을 볼 수 있으므로
    # 여기서 명확히 알려줘도 노출되는 정보가 없다.
    #
    # **비교를 대소문자 없이 한다.** 이 앱의 나머지(register·login·forgot)는 이메일을
    # 정규화하지 않고 그대로 비교하는데, 여기서만 lower()로 저장한다. 그래서 단순
    # 동등 비교를 쓰면 'Bob@x.com'으로 가입한 계정이 'bob@x.com' 초대의 중복 검사를
    # 통과해버린다 → 같은 메일함에 계정이 둘 생긴다. 소각 단계의 unique 제약도
    # 대소문자를 구분하므로 거기서도 못 걸린다. 그래서 이 검사가 유일한 방어다.
    if (
        db.scalar(select(User).where(func.lower(User.email) == email)) is not None
    ):
        raise HTTPException(status_code=400, detail="이미 가입된 주소야")
    # 살아 있는 초대가 있으면 하나로 유지한다. 같은 사람에게 유효 링크가 여러 개
    # 떠다니면 '취소했다'가 거짓이 된다 — 하나만 버려도 나머지로 들어올 수 있다.
    now = datetime.now(UTC)
    live = db.scalar(
        select(Invite).where(
            Invite.email == email,
            Invite.used_at.is_(None),
            Invite.expires_at > now,
        )
    )
    if live is not None:
        raise HTTPException(
            status_code=409, detail="아직 안 쓴 초대가 있어. 취소하고 다시 발급해"
        )

    token = new_invite_token()
    invite = Invite(
        email=email,
        token_hash=hash_invite_token(token),
        role=data.role,
        created_by_id=admin.id,
        expires_at=now + timedelta(days=data.expires_days),
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    url = f"{settings.frontend_base_url}/register?token={token}"
    # 발급자는 지금 이 요청의 관리자라 조회할 필요가 없다. 안 채우면 방금 만든
    # 줄만 '발급자 없음'으로 보이고, 새로고침하면 채워진다 — 그 어긋남이 더 헷갈린다.
    row = InviteOut.model_validate(invite).model_copy(
        update={"created_by_email": admin.email}
    )
    # 주소가 실재하는지 알려줄 유일한 단서. 초대제는 메일을 한 통도 안 보내므로
    # 오타나 남의 주소가 들어가도 침묵으로 지나간다 — 여기서 말해주지 않으면
    # 비번 재설정이 필요해지는 날까지 아무도 모른다.
    # 발급을 막지는 않는다. 검증 안 된 주소로도 초대는 유효하고(가입엔 메일이
    # 필요 없다), 관리자가 사정을 알고 보내는 경우가 대부분이라서다.
    # 여기서 절대 예외가 새면 안 된다. 초대 행은 위에서 **이미 커밋됐고**, 원문
    # 토큰은 이 응답에만 실린다 — 500이 나가면 초대는 DB에 남는데 링크는 영영
    # 사라져서 취소하고 다시 발급하는 수밖에 없다. 부가 정보가 본 기능을 망치는
    # 전형적인 모양이라, 서비스가 이미 삼키더라도 호출부에서 한 번 더 막는다.
    # **여기서 커넥션을 놓는다 — 위치가 전부다.** 아래 recipient_status는 SES 호출
    # 2회(각 connect 2 + read 3초)라 최악 ≈10초인데, `:222`의 db.refresh가 연 트랜잭션이
    # 그동안 풀(core/database.py) 한 칸을 `idle in transaction`으로 묶는다. ai.py:342·uploads.py:106과
    # 같은 패턴의 세 번째 자리다.
    # ⚠️ **`row` 조립(위 3줄) 뒤여야 한다.** 그 앞에서 커밋하면 expire_on_commit 때문에
    #    `invite`·`admin`을 읽는 순간 refresh SELECT가 나가 방금 반납한 커넥션을 다시
    #    빌린다. 여기서 그게 터지면 초대는 커밋됐는데 **원문 링크는 영영 사라진다.**
    #    (2026-08-11 동료 리뷰 — 변론이 이 위치를 짚었다)
    db.commit()
    try:
        verified = recipient_status(email)["verified"]
    except Exception:
        verified = None
    return InviteCreated(**row.model_dump(), url=url, recipient_verified=verified)


@router.delete("/invites/{invite_id}", status_code=204)
def revoke_invite(invite_id: int, db: Session = Depends(get_db)):
    """초대 취소(삭제). 아직 안 쓴 것만 지운다.

    이미 소각된 초대를 지우면 '누가 이 계정을 들였나'의 기록이 사라진다.
    계정을 없애고 싶으면 그건 가입자 관리에서 할 일이지 여기가 아니다."""
    invite = db.get(Invite, invite_id)
    if invite is None:
        raise HTTPException(status_code=404, detail="초대를 찾을 수 없음")
    if invite.used_at is not None:
        raise HTTPException(status_code=400, detail="이미 사용된 초대는 지울 수 없어")
    db.delete(invite)
    db.commit()
