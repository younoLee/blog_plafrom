"""이메일 대소문자 — 조회는 무시하고, 저장은 중복을 못 만든다.

2026-08-07에 조회만 대소문자 무시로 고쳤고(`_find_user_by_email`) 유니크는 원문
그대로였다. 그 사이가 이 파일이 지키는 자리다: `Bob@x.com`과 `bob@x.com`이 **둘 다
만들어질 수 있으면**, 그 뒤로 대소문자 무시 조회는 둘 중 아무 행이나 돌려준다.
로그인이 어느 계정으로 붙는지가 행 순서에 달리고, 비번 재설정이 사람이 안 쓰는
쪽을 고칠 수 있다. 그래서 '조회가 맞다'만으로는 부족하고 **만들어질 수 없어야** 한다.

2026-08-09에 `uq_users_email_lower`로 닫았다. 아래 첫 테스트가 그 인덱스가 실제로
DDL에 나갔는지를 본다 — 모델에만 있고 마이그레이션에 없으면 로컬은 초록이고
프로드 기동에서 처음 드러난다(2026-08-07에 정확히 그렇게 당했다).
"""
import pytest
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.security import hash_password
from app.models.user import User


def test_대소문자만_다른_계정은_만들어지지_않는다(db, make_user):
    """DB 차원의 차단. 애플리케이션 코드를 통째로 우회해도 막혀야 한다."""
    make_user(email="Case@Example.com")

    db.add(User(
        email="case@example.com",  # 대소문자만 다르다
        hashed_password=hash_password("password123"),
        role="writer",
        email_verified=True,
    ))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_원문이_같은_중복은_여전히_막힌다(db, make_user):
    """새 인덱스를 넣으면서 원래 있던 unique=True를 깨뜨리지 않았는지."""
    make_user(email="same@example.com")

    db.add(User(
        email="same@example.com",
        hashed_password=hash_password("password123"),
        role="writer",
        email_verified=True,
    ))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_로그인은_대소문자를_섞어_쳐도_된다(client, make_user):
    """초대는 주소를 소문자로 저장한다. 초대받은 사람이 평소 쓰던 대로 대문자를
    섞어 치면, 조회가 원문 비교이던 시절엔 **맞는 비번인데 401**이었다."""
    make_user(email="mixed@example.com", password="password123")

    r = client.post("/api/auth/login",
                    json={"email": "MiXeD@Example.COM", "password": "password123"})
    assert r.status_code == 200, r.text
    assert r.json()["access_token"]


def test_가입이_열려도_대소문자_다른_기존_계정을_신규로_읽지_않는다(
    client, db, make_user, monkeypatch
):
    """`register`는 프로드에서 403이지만 코드는 살아 있다. 여기서 '신규'로 오판하면
    INSERT까지 갔다가 유니크 인덱스에 걸리고, IntegrityError 분기가 그걸 동시 가입
    레이스로 오인해 "확인 메일을 보냈어"를 돌려준다 — 메일은 아무도 안 보낸다."""
    monkeypatch.setattr(settings, "allow_signup", True)
    user = make_user(email="dup@example.com", password="original123", verified=False)
    before = user.hashed_password

    r = client.post("/api/auth/register",
                    json={"email": "DUP@example.com", "password": "attacker123"})
    assert r.status_code == 202, r.text

    # 미인증 계정이라 '기존' 분기를 타서 해시가 갱신돼야 한다(계정 선점 방어).
    # 신규로 읽혔다면 이 값이 그대로고, 계정도 하나 더 늘어난다.
    db.refresh(user)
    assert user.hashed_password != before
    assert db.query(User).filter(User.email.ilike("dup@example.com")).count() == 1
