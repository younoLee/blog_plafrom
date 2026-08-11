"""미인증 계정 자동 정리 — 이 저장소의 **유일한 대량 DELETE**.

2026-08-11 공백검사 기준 테스트가 0건이었다. 즉 `delete(User).where(...)`의 조건이
뒤집히거나 빠져도 CI가 초록이었다는 뜻이다:
  · `<` 가 `>` 가 되면 **방금 가입한 계정만** 지운다
  · `.is_(False)` 가 빠지면 24시간 지난 **모든 계정**을 지운다
게다가 `except Exception: return 0`이 그 실패를 통째로 삼켜 로그도 안 남는다.
이 앱은 계정 생성 경로가 초대 하나뿐이라(가입 영구 폐쇄) 복구가 관리자 수작업이다.

`cleanup_unverified`는 `SessionLocal()`로 자기 커넥션을 열므로 `db` 픽스처의
롤백 트랜잭션 밖에서 돈다 → test_status.py와 같이 실제로 커밋하고 finally에서 지운다.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete

from app.core.database import SessionLocal
from app.models.user import User
from app.services.cleanup import cleanup_unverified


def _seed(session, *, email, verified, age_hours):
    u = User(
        email=email,
        hashed_password="x",
        role="pending",
        email_verified=verified,
        created_at=datetime.now(UTC) - timedelta(hours=age_hours),
    )
    session.add(u)
    return u


def test_cleanup_deletes_only_old_unverified():
    """네 경우를 한 번에 — 지워야 할 하나만 지워지는가."""
    session = SessionLocal()
    ids = []
    try:
        old_unverified = _seed(
            session, email="cl-old-unverified@test.local", verified=False, age_hours=48
        )
        fresh_unverified = _seed(
            session, email="cl-fresh-unverified@test.local", verified=False, age_hours=1
        )
        old_verified = _seed(
            session, email="cl-old-verified@test.local", verified=True, age_hours=48
        )
        fresh_verified = _seed(
            session, email="cl-fresh-verified@test.local", verified=True, age_hours=1
        )
        session.commit()
        ids = [old_unverified.id, fresh_unverified.id, old_verified.id, fresh_verified.id]
        target_id = old_unverified.id
        survivors = [fresh_unverified.id, old_verified.id, fresh_verified.id]

        n = cleanup_unverified()
        assert n >= 1

        session.expire_all()
        assert session.get(User, target_id) is None, "24h 지난 미인증 계정이 안 지워졌다"
        for sid in survivors:
            assert session.get(User, sid) is not None, (
                f"지우면 안 되는 계정(id={sid})이 지워졌다 — 조건이 뒤집혔는지 확인"
            )
    finally:
        if ids:
            session.execute(delete(User).where(User.id.in_(ids)))
            session.commit()
        session.close()


def test_cleanup_ttl_boundary_is_respected():
    """ttl_hours 인자가 실제로 경계로 쓰이는가 (상수만 읽고 무시하지 않는지)."""
    session = SessionLocal()
    ids = []
    try:
        u = _seed(session, email="cl-boundary@test.local", verified=False, age_hours=5)
        session.commit()
        # id를 **미리 꺼내 둔다** — 행이 지워진 뒤 u.id를 읽으면 SQLAlchemy가 refresh를
        # 시도하다 ObjectDeletedError를 낸다(그래서 첫 판이 여기서 깨졌다).
        uid = u.id
        ids = [uid]

        # 경계 밖(10시간 기준) → 살아 있어야 한다
        cleanup_unverified(ttl_hours=10)
        session.expire_all()
        assert session.get(User, uid) is not None, "ttl_hours 인자가 무시됐다"

        # 경계 안(1시간 기준) → 지워져야 한다
        cleanup_unverified(ttl_hours=1)
        session.expire_all()
        assert session.get(User, uid) is None
    finally:
        if ids:
            session.execute(delete(User).where(User.id.in_(ids)))
            session.commit()
        session.close()
