from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.ratelimit import limiter
from app.core.security import (
    create_access_token,
    create_email_token,
    decode_email_token,
    hash_invite_token,
    hash_password,
    verify_password,
)
from app.models.invite import Invite
from app.models.user import User
from app.schemas.invite import InvitePreview, InviteRedeem, InviteToken
from app.schemas.user import (
    DisplayNameUpdate,
    ForgotPasswordRequest,
    RegisterRequest,
    ResetPasswordRequest,
    Token,
    UserCreate,
    UserRead,
)
from app.services.email import (
    send_already_registered_email,
    send_reset_email,
    send_verification_email,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=202)
@limiter.limit("5/hour")  # 한 IP당 시간당 5번까지만 가입 (대량가입 속도 차단)
def register(request: Request, data: RegisterRequest, background: BackgroundTasks, db: Session = Depends(get_db)):
    # 초대제 게이트: 기본으로 닫혀 있다. 프론트 폼 제거만으론 이 라우트가 살아 있어
    # 아무 주소로 인증메일을 보낼 수 있었다(SES 바운스). 방어는 백엔드에 있어야 한다.
    if not settings.allow_signup:
        raise HTTPException(
            status_code=403,
            detail="가입은 초대제로 운영돼. 초대 링크가 있으면 그 링크로 가입하면 돼.",
        )
    # 계정 존재 여부를 HTTP 응답으로 노출하지 않으려고 신규/기존 구분 없이 동일한 202 응답.
    # 실제 안내는 '메일로만' 간다 (forgot-password와 같은 패턴) → 이메일 enumeration 방지.
    # 조회도 대소문자를 무시한다. 안 하면 `Bob@x.com`이 '신규'로 읽혀 INSERT까지 갔다가
    # lower(email) 유니크 인덱스에 걸린다 — 아래 IntegrityError 분기가 그걸 동시 가입
    # 레이스로 오인해 "확인 메일을 보냈어"를 돌려주는데, 메일은 아무도 안 보낸다.
    existing = _find_user_by_email(db, data.email)
    if existing is None:
        # 신규: pending + 미인증으로 생성 후 인증메일 (관리자 승격은 DB에서만)
        user = User(
            email=data.email,
            hashed_password=hash_password(data.password),
            role="pending",
            email_verified=False,
        )
        db.add(user)
        try:
            db.commit()
        except IntegrityError:
            # 동시 가입 레이스: 그 찰나 다른 요청이 같은 이메일을 만듦(email unique 충돌).
            # 500 대신 일반 응답 유지(존재 여부 노출 안 함) — 이미 메일은 그쪽 요청이 보냄.
            db.rollback()
            return {"message": "확인 메일을 보냈어. 메일함을 확인해줘."}
        db.refresh(user)
        token = create_email_token(user.id, purpose="verify")
        link = f"{settings.frontend_base_url}/verify?token={token}"
        background.add_task(send_verification_email, user.email, link)
    elif not existing.email_verified:
        # 기존이지만 아직 미인증: 인증메일 재발송 (가입 완료 못 한 사람 도움)
        #
        # ⚠️ 비밀번호 해시를 **반드시 갱신**한다. 안 하면 계정 선점이 된다:
        #   공격자가 victim@x.com으로 먼저 가입(해시 = 공격자 비번) → 진짜 피해자가
        #   같은 주소로 가입하면 이 분기를 타고 인증 메일만 피해자에게 간다 →
        #   피해자가 링크를 누르면 email_verified=True가 되는데 **비밀번호는 공격자 것**.
        #   그 순간 공격자가 피해자 신원의 '검증된' 계정으로 로그인한다.
        # 미인증 계정은 아직 아무 데이터도 없으므로 마지막 요청의 비번으로 덮어써도 안전하다.
        # token_version도 올려 그전에 발급된 링크를 무효화한다.
        existing.hashed_password = hash_password(data.password)
        existing.token_version += 1
        db.commit()
        db.refresh(existing)
        token = create_email_token(existing.id, purpose="verify")
        link = f"{settings.frontend_base_url}/verify?token={token}"
        background.add_task(send_verification_email, existing.email, link)
    else:
        # 기존 + 인증완료: '이미 가입됨' 안내메일 (HTTP 응답으로는 노출 안 함)
        background.add_task(
            send_already_registered_email,
            existing.email,
            f"{settings.frontend_base_url}/login",
        )
    return {"message": "확인 메일을 보냈어. 메일함을 확인해줘."}


# ── 초대 가입 ────────────────────────────────────────────────────────────────
#
# 위의 register와 나란히 두되 **분리한다.** 같은 라우트에 토큰 분기를 넣지 않은 이유:
# register는 이메일 enumeration을 막으려고 신규/기존을 안 가리고 항상 202를 준다.
# 초대 가입은 반대로 "만료됐다"를 분명히 말해줘야 쓸 수 있는데, 두 규칙을 한
# 함수에 넣으면 어느 쪽 응답 규칙이 적용되는지가 분기마다 헷갈린다.
# 분리하면 각자의 규칙이 함수 하나에 하나씩만 산다.
#
# 그리고 초대 가입에는 enumeration 걱정이 없다 — 유효한 토큰을 쥔 사람만 의미 있는
# 응답을 받고, 그 토큰은 관리자가 그 주소를 위해 직접 발급한 것이다.

# 유효하지 않은 초대에 대한 **단일** 응답. 만료/이미 사용됨/위조를 구분해 알려주면
# 그것 자체가 오라클이 된다("이 토큰은 존재는 하는군"). 셋 다 같은 말을 준다.
_INVITE_INVALID = "이 초대 링크는 유효하지 않아 (만료됐거나 이미 사용됐어)"


def _live_invite(token: str, now: datetime):
    """'아직 쓸 수 있는 초대'의 조건. 미리보기(읽기)와 소각(쓰기)이 **반드시 같은
    판정**을 써야 한다 — 조건을 두 군데에 따로 적어두면 한쪽만 고쳤을 때
    미리보기는 "유효하다"며 폼을 띄우고 소각은 거절하는 상태가 되고, 그건
    테스트가 각각 통과하므로 CI로도 안 잡힌다."""
    return (
        Invite.token_hash == hash_invite_token(token),
        Invite.used_at.is_(None),
        Invite.expires_at > now,
    )


@router.post("/invite", response_model=InvitePreview)
@limiter.limit("30/hour")  # 토큰 유효성을 묻는 창구라 두드리는 속도를 제한한다
def preview_invite(
    request: Request, data: InviteToken, db: Session = Depends(get_db)
):
    """초대 링크를 연 사람에게 '어떤 주소로 가입되는지'를 보여준다.

    화면에서 이메일을 읽기 전용으로 띄우기 위한 것이다. 토큰을 이미 쥔 사람에게만
    나가므로 주소 노출이 아니다 — 그 주소를 위해 발급된 토큰이니까.

    **읽기인데 POST인 이유**는 토큰을 URL에 싣지 않기 위해서다. 초대 토큰은 그
    자체가 자격증명이고, uvicorn 액세스 로그는 쿼리스트링까지 찍는다 — GET으로
    두면 원문 토큰이 로그에 평문으로 남아 '해시로만 저장한다'가 거짓이 된다.
    (실측: `GET /api/auth/invite?token=...`이 로그 라인에 그대로 나온다.)"""
    invite = db.scalar(
        select(Invite).where(*_live_invite(data.token, datetime.now(UTC)))
    )
    if invite is None:
        raise HTTPException(status_code=404, detail=_INVITE_INVALID)
    return InvitePreview(email=invite.email, role=invite.role)


@router.post("/register/invite", response_model=Token, status_code=201)
@limiter.limit("10/hour")
def redeem_invite(
    request: Request, data: InviteRedeem, db: Session = Depends(get_db)
):
    """초대 토큰을 소각하고 계정을 만든다. `allow_signup`과 무관하게 동작한다.

    **이메일 인증 메일을 보내지 않고 email_verified=True로 만든다.** 근거: 인증
    메일의 목적은 '이 주소가 실제로 존재하고 신청자의 것인가'인데, 초대제에선
    주소를 관리자가 골랐다. 관리자의 보증이 이미 그 답이다. 덤으로 가입 경로가
    SES에서 완전히 풀린다 — 샌드박스가 막고 있던 게 정확히 이 지점이었다.
    (role은 초대에 적힌 값. 기본은 pending이라 글쓰기는 여전히 관리자 승인이 필요하다.)
    """
    now = datetime.now(UTC)
    # 소각을 **조건부 UPDATE 한 방**으로 한다. 조건이 걸린 UPDATE는 행 잠금을 잡고,
    # 뒤에 온 요청은 앞의 커밋 후 조건을 다시 평가해 0행을 돌려받는다.
    # 읽고-쓰기와의 실제 차이는 models/invite.py에 재본 대로 적어뒀다 —
    # 계정 복제가 아니라 **진 쪽이 받는 안내**가 갈린다(여기선 "링크가 이미 쓰였어",
    # 읽고-쓰기면 유니크 충돌을 타서 "이미 가입된 주소야").
    claimed = db.execute(
        update(Invite)
        .where(*_live_invite(data.token, now))
        .values(used_at=now)
        .returning(Invite.id, Invite.email, Invite.role)
        .execution_options(synchronize_session=False)
    ).first()
    if claimed is None:
        raise HTTPException(status_code=400, detail=_INVITE_INVALID)
    invite_id, email, role = claimed

    user = User(
        email=email,
        hashed_password=hash_password(data.password),
        role=role,
        email_verified=True,
    )
    db.add(user)
    try:
        db.flush()  # id가 필요하다(아래 used_by_id). 커밋은 마지막에 한 번.
    except IntegrityError:
        # 초대 발급 시점엔 없던 계정이 그 사이 생긴 경우(email unique 충돌).
        # 롤백하면 위의 소각도 같이 되돌아간다 — 같은 트랜잭션이라 초대는 안 타버린다.
        db.rollback()
        raise HTTPException(status_code=400, detail="이미 가입된 주소야") from None

    # 누가 이 계정을 들였나 — 초대제에서는 이게 감사 기록이다.
    db.execute(
        update(Invite)
        .where(Invite.id == invite_id)
        .values(used_by_id=user.id)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    # refresh를 지우지 말 것 — 이건 정리용이 아니라 **토큰에 필요한 값을 읽어오는**
    # 단계다. token_version은 Python 기본값이 없고 server_default='0'이라 INSERT
    # 직후엔 파이썬 쪽이 비어 있다. 여기서 채우지 않으면 아래 토큰에 None이 실린다.
    db.refresh(user)
    # 바로 로그인시킨다. 초대 링크를 눌러 비번을 정한 사람에게 로그인 화면을 다시
    # 보여줄 이유가 없다(이메일 인증 단계가 없으므로 기다릴 것도 없다).
    return Token(access_token=create_access_token(user.id, user.token_version))


@router.post("/verify", response_model=UserRead)
def verify_email(token: str, db: Session = Depends(get_db)):
    # 메일 링크의 토큰으로 이메일 인증 처리 (purpose=verify인 토큰만 통과)
    decoded = decode_email_token(token, purpose="verify")
    if decoded is None:
        raise HTTPException(status_code=400, detail="유효하지 않거나 만료된 링크야")
    user_id, _ = decoded
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없음")
    user.email_verified = True
    db.commit()
    db.refresh(user)
    return user


# 이메일로 계정을 찾을 때 쓰는 조회. **대소문자를 무시한다.**
#
# 왜 바꿨나 — 2026-08-07 초대제 가입을 붙이면서 잠금 사고가 생길 수 있게 됐다.
# 초대는 주소를 관리자가 입력하고 소문자로 저장한다(routers/admin.py). 그래서
# 'Bob@Example.com'으로 초대하면 계정은 'bob@example.com'이 된다. 그런데 로그인은
# 원문 그대로 비교했으므로, Bob이 평소 쓰는 대로 대문자를 섞어 치면 **맞는 비번인데도
# 401**이고, 비번 재설정은 202를 주면서 메일을 안 보낸다 — 어디에도 단서가 없는 잠금이다.
# 초대 전에는 가입 때 친 문자열을 로그인 때도 그대로 쳤으므로 이 어긋남이 없었다.
#
# 도메인부는 원래 대소문자를 안 가리고, 로컬부를 가리는 메일 서비스는 사실상 없다.
# 그래서 무시하는 쪽이 맞다.
#
# 2026-08-09: 그때 "구조적으로 막으려면 lower(email) 유니크 인덱스가 필요하다"고
# 적어둔 것을 실제로 걸었다(`uq_users_email_lower`, models/user.py). 이제 이 조회가
# 두 행을 만날 수 없다 — 그전까지는 만나면 **둘 중 아무 행이나** 돌려줬다.
def _find_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(func.lower(User.email) == email.lower()))


@router.post("/login", response_model=Token)
@limiter.limit("10/minute")  # 무차별 비번 대입 속도 제한
def login(request: Request, data: UserCreate, db: Session = Depends(get_db)):
    user = _find_user_by_email(db, data.email)
    # 사용자 없거나 비밀번호 틀리면 동일한 401 (어느 쪽이 틀렸는지 안 알려줌 = 보안)
    if user is None or not verify_password(data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 틀렸어")
    # 차단된 계정은 로그인 불가
    if user.role == "banned":
        raise HTTPException(status_code=403, detail="차단된 계정이야")
    # 이메일 미인증이면 로그인 불가 (봇 대량가입 차단)
    if not user.email_verified:
        raise HTTPException(status_code=403, detail="이메일 인증이 필요해 (메일함 확인)")
    return Token(access_token=create_access_token(user.id, user.token_version))


@router.post("/forgot-password", status_code=202)
@limiter.limit("5/hour")  # 메일 폭탄 방지
def forgot_password(
    request: Request,
    data: ForgotPasswordRequest,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
):
    user = _find_user_by_email(db, data.email)
    # 가입돼 있고 차단 안 된 계정에만 실제 발송. 단 응답은 항상 동일(존재 여부 노출 안 함)
    if user is not None and user.role != "banned":
        # ver=현재 token_version → 재설정 후 token_version이 바뀌면 이 토큰은 무효(1회용)
        token = create_email_token(
            user.id, purpose="reset", expire_hours=1, ver=user.token_version
        )
        link = f"{settings.frontend_base_url}/reset?token={token}"
        background.add_task(send_reset_email, user.email, link)
    return {"message": "재설정 링크를 보냈어 (가입된 이메일이라면)"}


# 이 파일의 리밋 축은 "**무인증으로 상태를 바꾸거나 메일을 쏘는 것**"이다 —
# register 5/h · invite preview 30/h · redeem 10/h · login 10/min · forgot 5/h가 전부
# 그 정의에 들어맞는다. **비밀번호를 무인증으로 바꾸는 유일한 입구인 여기만 빠져 있었다.**
# (2026-08-11 동료 리뷰. `/auth/verify`는 allow_signup=False라 토큰 발급 자체가 없어 제외)
#
# 20/hour로 넉넉하게 둔다. slowapi는 프로세스 메모리 IP 카운터라 NAT 뒤 공용 IP면
# 정상 사용자끼리 서로를 막는데, 재설정은 "지금 못 하면 계정이 잠긴 것과 같은" 화면이라
# 목록 조회의 오탐과 비용이 다르다. 브루트포스는 이미 서명+1시간 만료+token_version
# 1회용이 막고 있으므로, 이 리밋의 목적은 남용 속도 제한이지 방어의 본체가 아니다.
@router.post("/reset-password", response_model=UserRead)
@limiter.limit("20/hour")
def reset_password(
    request: Request, data: ResetPasswordRequest, db: Session = Depends(get_db)
):
    # reset 목적 토큰만 통과
    decoded = decode_email_token(data.token, purpose="reset")
    if decoded is None:
        raise HTTPException(status_code=400, detail="유효하지 않거나 만료된 링크야")
    user_id, tok_ver = decoded
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없음")
    # 토큰의 ver가 현재와 다르면 = 이미 한 번 쓴(또는 그 사이 비번 바뀐) 토큰 → 거부(1회용)
    if user.token_version != tok_ver:
        raise HTTPException(status_code=400, detail="이미 사용했거나 만료된 링크야")
    user.hashed_password = hash_password(data.new_password)
    user.token_version += 1  # 비번 바뀌면 기존 토큰·이 재설정 토큰 모두 무효화
    db.commit()
    db.refresh(user)
    return user


@router.get("/me", response_model=UserRead)
def me(current: User = Depends(get_current_user)):
    return current


@router.patch("/me", response_model=UserRead)
def update_me(
    data: DisplayNameUpdate,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """내 표시명을 바꾼다. **비밀번호는 건드리지 않는다.**

    2026-08-14에 구독 화면이 "회원 · 회원 · 회원"으로 보인다는 신고에서 나왔다.
    표시명은 DB에 컬럼이 있고 화면 네 곳(구독·댓글·알림·사이드바)이 그걸 읽는데,
    **정할 방법이 제품에 없었다.** 유일한 경로가 `create_user.py --display-name`이고
    그 스크립트는 같은 실행에서 비밀번호를 새로 만들어 덮어쓴다 — 이름 하나 바꾸려다
    로그인을 잃는 구조였다.

    빈 문자열·공백만 주면 NULL로 되돌린다(= '안 정함'). 그러면 화면은 다시 폴백을 쓴다.
    이름을 지울 방법이 없으면 한 번 정한 사람이 갇힌다.

    ⚠️ 이 이름은 **공개된다** — 댓글 작성자명과 구독 목록에 그대로 나간다.
    그래서 이메일에서 유도하지 않는다(주소가 새는 경로가 된다). 사람이 직접 고른 값만 쓴다.
    """
    name = data.display_name.strip()
    current.display_name = name or None
    db.commit()
    db.refresh(current)
    return current


@router.post("/logout", status_code=204)
def logout(current: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """로그아웃 — 이 계정에 발급된 **모든** 토큰을 무효화한다.

    2026-08-12 보안 검사가 "레버는 있는데 손잡이가 없다"고 적어둔 자리다.
    `token_version`은 비밀번호 재설정·초대 재발급에서만 올라갔고, 사용자가 스스로
    세션을 끊을 방법은 저장소 어디에도 없었다. 기기를 잃어버렸을 때 할 수 있는 게
    비밀번호 재설정뿐이었다는 뜻이다.

    **왜 기기 단위가 아닌가.** 토큰은 서명된 JWT이고 서버에 세션 표가 없다. 특정
    토큰만 죽이려면 폐기 목록(jti)이라는 표가 하나 더 필요한데, 그 표는 만료 전까지
    지울 수 없어 계속 자란다. 지금 있는 레버(`token_version`)는 계정 단위이고,
    로그아웃의 진짜 용도(기기 분실)에는 계정 단위가 오히려 맞는 답이다.

    ⚠️ 이 응답을 받은 **다른 기기**는 그 즉시 401을 받는다. 프론트가 그 401에서
    토큰을 지우고 화면을 비로그인으로 되돌리지 않으면 '로그인된 것처럼 보이는데
    아무것도 안 되는' 상태가 된다 — 그래서 프론트의 401 전역 처리(`api/http.ts`의
    `request`)가 **이 엔드포인트의 선행 조건**이었다. 순서를 뒤집지 말 것.

    204를 주는 이유: 돌려줄 내용이 없다. 그리고 멱등하다 — 이미 무효인 토큰으로는
    여기 도달조차 못 하고(401), 유효한 토큰으로 두 번 부르면 두 번째는 401이다.
    """
    current.token_version += 1
    db.commit()
