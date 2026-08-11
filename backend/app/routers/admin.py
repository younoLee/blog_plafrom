from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session, aliased

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import require_admin
from app.core.security import hash_invite_token, new_invite_token
from app.models.invite import Invite
from app.models.post import Post
from app.models.user import User
from app.schemas.invite import InviteCreate, InviteCreated, InviteOut
from app.schemas.user import UserRead
from app.services.infra import gather_infra
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
    return data


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


@router.post("/users/{user_id}/approve", response_model=UserRead)
def approve_user(user_id: int, db: Session = Depends(get_db)):
    # 승인: pending → writer (글쓰기 허용)
    user = _get_user_or_404(user_id, db)
    if user.role == "admin":
        raise HTTPException(status_code=400, detail="관리자 계정은 변경할 수 없어")
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
    user.role = "banned"
    user.token_version += 1  # 차단 즉시 기존 토큰 무효화
    db.commit()
    db.refresh(user)
    return user


@router.post("/users/{user_id}/unban", response_model=UserRead)
def unban_user(user_id: int, db: Session = Depends(get_db)):
    # 차단 해제: pending으로 되돌림(재승인 필요)
    user = _get_user_or_404(user_id, db)
    if user.role != "banned":
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
    user.is_pro = not user.is_pro
    # 켤 땐 만료 없음(None). 안 그러면 과거 결제의 pro_until이 남아 있어 다음 요청에서
    # _expire_pro_if_due(deps.py)가 즉시 되돌린다 → 관리자 수동 부여가 조용히 무효화됐다.
    if user.is_pro:
        user.pro_until = None
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
    db.execute(delete(Post).where(Post.owner_id == user_id))
    # author_subscriptions는 users FK ondelete CASCADE라 user 삭제 시 자동 정리
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
    # 그동안 풀 15칸 중 1칸을 `idle in transaction`으로 묶는다. ai.py:342·uploads.py:106과
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
