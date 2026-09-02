"""인증의 보안 속성 — 이메일인증/비번재설정 흐름 + 토큰 무효화·혼용 차단.
로그인 성공만이 아니라 '세션이 제대로 끊기는가'를 건다."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.core.config import settings
from app.core.security import create_email_token
from app.models.user import LoginFailure
from app.routers.auth import LOGIN_FAIL_MAX, LOGIN_FAIL_WINDOW


# ── 초대제 게이트 ────────────────────────────────────────────────────────────
def test_register_closed_when_signup_disabled(client, monkeypatch):
    """allow_signup=False(운영 기본)면 register가 403으로 닫힌다. 프론트 폼 제거만으론
    라우트가 살아 아무 주소로 인증메일을 보낼 수 있었다(SES 하드바운스) — 백엔드에서 막는다.
    (conftest의 autouse open_signup이 기본을 열어두므로 여기서 되돌려 검증)"""
    monkeypatch.setattr(settings, "allow_signup", False)
    r = client.post(
        "/api/auth/register",
        json={"email": "closed@test.com", "password": "password123"},
    )
    assert r.status_code == 403


# ── 이메일 인증 ──────────────────────────────────────────────────────────────
def test_verify_email_flow(client, make_user):
    user = make_user(role="pending", verified=False)
    token = create_email_token(user.id, purpose="verify")
    r = client.post(f"/api/auth/verify?token={token}")
    assert r.status_code == 200
    assert r.json()["email_verified"] is True


def test_verify_invalid_token_400(client):
    assert client.post("/api/auth/verify?token=garbage.token.x").status_code == 400


# ── 비번 재설정: 성공 + 기존 세션 무효화 ──────────────────────────────────────
def test_reset_password_changes_pw_and_revokes_old_tokens(
    client, make_user, auth_headers
):
    user = make_user(role="writer", password="oldpassword1")
    old_headers = auth_headers(user)  # 재설정 전 토큰(token_version=0)
    token = create_email_token(user.id, purpose="reset", ver=user.token_version)

    r = client.post(
        "/api/auth/reset-password",
        json={"token": token, "new_password": "newpassword1"},
    )
    assert r.status_code == 200

    # 비번 바뀌면 기존 액세스 토큰 즉시 무효 (token_version++)
    assert client.get("/api/auth/me", headers=old_headers).status_code == 401
    # 새 비번으로는 로그인됨
    lr = client.post(
        "/api/auth/login", json={"email": user.email, "password": "newpassword1"}
    )
    assert lr.status_code == 200


def test_reset_token_is_single_use(client, make_user):
    user = make_user(role="writer")
    token = create_email_token(user.id, purpose="reset", ver=user.token_version)
    first = client.post(
        "/api/auth/reset-password", json={"token": token, "new_password": "newpassword1"}
    )
    assert first.status_code == 200
    # 같은 토큰 재사용 → ver 불일치로 거부(1회용)
    second = client.post(
        "/api/auth/reset-password", json={"token": token, "new_password": "another1234"}
    )
    assert second.status_code == 400


# ── 토큰 혼용 차단 ───────────────────────────────────────────────────────────
def test_email_token_cannot_be_used_as_bearer(client, make_user):
    user = make_user(role="writer")
    email_token = create_email_token(user.id, purpose="verify")
    # purpose가 박힌 이메일 토큰은 로그인 토큰으로 못 씀(토큰 혼동 방지)
    r = client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {email_token}"}
    )
    assert r.status_code == 401


def test_verify_purpose_token_rejected_on_reset(client, make_user):
    user = make_user(role="writer")
    verify_token = create_email_token(user.id, purpose="verify", ver=user.token_version)
    # verify 목적 토큰을 reset 엔드포인트에 쓰면 purpose 불일치 → 거부
    r = client.post(
        "/api/auth/reset-password",
        json={"token": verify_token, "new_password": "newpassword1"},
    )
    assert r.status_code == 400


# ── 미인증 계정 선점(account pre-hijacking) ──────────────────────────────────
def test_reregister_unverified_replaces_password(client, db):
    """미인증 계정에 같은 이메일로 다시 가입하면 **비밀번호가 갱신돼야** 한다.

    안 그러면 계정 선점이 된다: 공격자가 피해자 이메일로 먼저 가입해 두면(미인증),
    피해자가 같은 주소로 가입할 때 인증 메일만 피해자에게 가고 저장된 해시는
    공격자 것으로 남는다. 피해자가 링크를 누르는 순간 '검증된' 계정이 되는데
    로그인은 공격자만 할 수 있다. (2026-07-22 보안검사에서 발견)
    """
    from app.models.user import User

    victim_email = "prehijack-target@test.com"
    attacker_pw, victim_pw = "attacker-password-1", "victim-password-2"

    # 1) 공격자가 피해자 이메일로 선점 가입 (미인증 상태로 생성됨)
    assert client.post(
        "/api/auth/register", json={"email": victim_email, "password": attacker_pw}
    ).status_code == 202

    # 2) 진짜 피해자가 같은 이메일로 가입 → 이 분기가 해시를 덮어써야 한다
    assert client.post(
        "/api/auth/register", json={"email": victim_email, "password": victim_pw}
    ).status_code == 202

    # 3) 피해자가 **재가입 뒤에 온** 메일 링크로 인증을 마친다.
    #    ver를 현재 token_version으로 맞춘다 — 2026-09-02부터 인증 토큰도 ver를 싣고
    #    verify가 그걸 대조한다(아래 test_재가입_전에_발급된_인증링크는_죽는다 참고).
    #    재가입이 token_version을 올렸으므로 여기서 0을 쓰면 400이 맞다.
    victim = db.query(User).filter(User.email == victim_email).one()
    assert client.post(
        "/api/auth/verify?token="
        + create_email_token(victim.id, purpose="verify", ver=victim.token_version)
    ).status_code == 200

    # 4) 공격자 비밀번호로는 못 들어가고, 피해자 비밀번호로는 들어가야 한다
    assert client.post(
        "/api/auth/login", json={"email": victim_email, "password": attacker_pw}
    ).status_code == 401
    assert client.post(
        "/api/auth/login", json={"email": victim_email, "password": victim_pw}
    ).status_code == 200


def test_login_sheds_load_when_bcrypt_slots_are_full(client, make_user):
    """bcrypt 칸이 다 차면 로그인은 기다리지 않고 즉시 503을 낸다.

    로그인은 계정 유무와 무관하게 cost 12 bcrypt를 항상 1회 돌린다(타이밍 공격 방어의
    대가다). 2026-08-26 부하검사 실측으로 그게 코어 하나를 ~1.5초 점유하고, vCPU당
    처리량이 30~40건/분뿐이라 **각자 10/분 한도를 지키는 IP 서너 개**만으로 t2.micro의
    유일한 vCPU가 찬다는 것이 확인됐다. 요청 수를 세는 리밋으로는 못 막는다 —
    세야 하는 건 요청이 아니라 CPU 시간이다.

    기다리지 않고 튕기는 것이 핵심이다. 핸들러가 전부 sync `def`라 대기하면 anyio
    스레드 칸을 붙들어, CPU 대신 스레드가 마르는 것으로 고장 모양만 바뀐다.
    """
    from app.routers import auth as auth_router

    user = make_user(role="writer", password="password123")

    # 칸을 전부 밖에서 잡아둔다 = 다른 요청이 이미 bcrypt를 돌고 있는 상황
    held = []
    while auth_router._BCRYPT_SLOTS.acquire(blocking=False):
        held.append(True)
    assert held, "세마포어가 칸을 하나도 안 내줬다"

    try:
        r = client.post(
            "/api/auth/login", json={"email": user.email, "password": "password123"}
        )
        assert r.status_code == 503
        assert r.json()["detail"]  # text/plain이 아니라 JSON으로 나간다
    finally:
        for _ in held:
            auth_router._BCRYPT_SLOTS.release()

    # 칸이 돌아오면 정상 로그인이 된다 — 세마포어가 새는지도 함께 본다
    r = client.post(
        "/api/auth/login", json={"email": user.email, "password": "password123"}
    )
    assert r.status_code == 200


def test_login_releases_bcrypt_slot_on_failure(client, make_user):
    """실패한 로그인도 칸을 돌려준다. finally가 빠지면 몇 번 만에 영구히 막힌다."""
    user = make_user(role="writer", password="password123")

    for _ in range(4):  # 상한(2)보다 넉넉히 — 새면 여기서 503이 난다
        r = client.post(
            "/api/auth/login", json={"email": user.email, "password": "wrong-password"}
        )
        assert r.status_code == 401

    r = client.post(
        "/api/auth/login", json={"email": user.email, "password": "password123"}
    )
    assert r.status_code == 200


def test_재가입_전에_발급된_인증링크는_죽는다(client, db):
    """순서가 반대인 선점 — **먼저** 가입한 사람의 인증 링크가 나중 가입 뒤에도
    살아 있으면 안 된다.

    2026-07-22 수정은 재가입 분기에서 해시를 덮어쓰는 것과 `token_version`을 올려
    그전 링크를 무효화하는 것, 두 가지였다(PROGRESS.md의 그 절). 그런데 무효화는
    실제로 아무 데도 걸려 있지 않았다: register가 인증 토큰에 `ver`을 안 실었고
    (`create_email_token`의 기본값 0), `/auth/verify`는 ver을 읽고도 비교하지 않았다.
    그래서 이 시나리오가 그대로 성립했다 —

      1) 피해자가 가입하고 링크 L을 받는다(미인증).
      2) 공격자가 같은 주소로 가입한다 → 저장된 해시가 공격자 것이 된다.
      3) 피해자가 L을 누른다 → 계정이 '인증됨'이 되는데 비밀번호는 공격자 것이다.

    즉 07-22가 막은 것과 같은 결과가 순서만 바꿔 남아 있었다. 2026-09-02에 ver를
    싣고 대조하게 고쳤고, 이 테스트가 그 회귀를 지킨다. 되돌리면 아래 400이 200이 된다.
    """
    from app.models.user import User

    email = "prehijack-order@test.com"
    victim_pw, attacker_pw = "victim-password-9", "attacker-password-9"

    # 1) 피해자가 먼저 가입 → 이때 나간 링크를 그대로 재현한다(ver = 그 시점 값)
    assert client.post(
        "/api/auth/register", json={"email": email, "password": victim_pw}
    ).status_code == 202
    account = db.query(User).filter(User.email == email).one()
    old_link_token = create_email_token(
        account.id, purpose="verify", ver=account.token_version
    )

    # 2) 공격자가 같은 주소로 뒤늦게 가입 → 해시가 공격자 것으로 덮인다
    assert client.post(
        "/api/auth/register", json={"email": email, "password": attacker_pw}
    ).status_code == 202

    # 3) 피해자가 옛 링크를 누른다 → 거부돼야 한다
    r = client.post(f"/api/auth/verify?token={old_link_token}")
    assert r.status_code == 400, r.text

    # 계정은 여전히 미인증이라 공격자도 로그인 못 한다(미인증은 403)
    db.refresh(account)
    assert account.email_verified is False


# ── 계정 단위 로그인 실패 카운터 ─────────────────────────────────────────────
#
# 왜 카운터를 손으로 심는가: 임계값(20)까지 실제 로그인을 돌리면 cost 12 bcrypt를
# 스무 번 돌려야 한다(요청당 0.3~1.5초). 검증 대상은 '해시가 느린가'가 아니라
# **판정과 해제 조건**이라, 세는 경로는 아래 test_실패는_실제로_누적된다가 몇 번의
# 진짜 실패로 따로 잠근다. 나머지는 상태를 심어 경계만 본다.
def _seed_failures(db, user, count, *, age=timedelta(0)):
    """그 계정에 '창이 age 전에 시작된 실패 count건'을 심는다. 창 시작 시각 반환."""
    started = datetime.now(UTC) - age
    db.add(LoginFailure(user_id=user.id, fail_count=count, window_start=started))
    db.commit()
    return started


def _failure_row(db, user):
    return db.scalar(select(LoginFailure).where(LoginFailure.user_id == user.id))


def test_상한_직전까지는_정상_로그인이_된다(client, db, make_user):
    """19건이 쌓여 있어도 맞는 비번은 통과한다. 경계에서 한 칸 일찍 잠그면 정상
    사용자가 이유도 모르고 막히는 쪽으로 틀린다."""
    user = make_user(role="writer", password="password123")
    _seed_failures(db, user, LOGIN_FAIL_MAX - 1)

    r = client.post(
        "/api/auth/login", json={"email": user.email, "password": "password123"}
    )

    assert r.status_code == 200, r.text
    # 성공했으니 카운터도 사라진다(다음 오타가 상한 바로 앞에서 시작하지 않게)
    assert _failure_row(db, user) is None


def test_상한을_넘기면_맞는_비번도_거절된다(client, db, make_user):
    """이게 이 기능의 본체다 — IP를 아무리 나눠도 계정당 시도가 창마다 20회에서 멈춘다."""
    user = make_user(role="writer", password="password123")
    _seed_failures(db, user, LOGIN_FAIL_MAX)

    r = client.post(
        "/api/auth/login", json={"email": user.email, "password": "password123"}
    )

    assert r.status_code == 401, r.text


def test_잠긴_계정과_없는_계정의_응답이_같다(client, db, make_user):
    """**열거를 만들지 않는 것이 잠금의 조건이다.**

    잠금이 다른 상태코드나 다른 문구("계정이 잠겼어")를 내면, 그 응답 하나가
    "이 주소에는 잠글 만한 계정이 있다"를 확정해 준다. register와 forgot-password가
    응답을 하나로 맞추느라 들인 공을 로그인이 되돌리는 셈이다. 셋 다 같은 401이어야 한다.
    """
    user = make_user(role="writer", password="password123")
    _seed_failures(db, user, LOGIN_FAIL_MAX)

    locked = client.post(
        "/api/auth/login", json={"email": user.email, "password": "password123"}
    )
    missing = client.post(
        "/api/auth/login",
        json={"email": "no-such-account@test.com", "password": "password123"},
    )

    assert locked.status_code == missing.status_code == 401
    assert locked.text == missing.text


def test_창이_지나면_저절로_풀린다(client, db, make_user):
    """영구 잠금이 아니다. 창이 지나면 아무도 손대지 않아도 다시 들어와진다 —
    안 그러면 남의 계정을 20번 틀려서 영영 잠그는 DoS가 된다."""
    user = make_user(role="writer", password="password123")
    _seed_failures(db, user, LOGIN_FAIL_MAX + 5, age=LOGIN_FAIL_WINDOW + timedelta(minutes=1))

    r = client.post(
        "/api/auth/login", json={"email": user.email, "password": "password123"}
    )

    assert r.status_code == 200, r.text


def test_잠긴_뒤의_실패가_잠금을_연장하지_않는다(client, db, make_user):
    """고정 창(fixed window)이지 슬라이딩이 아니다. 실패할 때마다 창이 밀리면
    공격자가 계속 두드려 남의 계정을 **무기한** 잠글 수 있다."""
    user = make_user(role="writer", password="password123")
    started = _seed_failures(db, user, LOGIN_FAIL_MAX)

    assert client.post(
        "/api/auth/login", json={"email": user.email, "password": "wrong-password"}
    ).status_code == 401

    row = _failure_row(db, user)
    assert row is not None
    assert row.fail_count == LOGIN_FAIL_MAX + 1  # 세기는 센다
    assert abs(row.window_start - started) < timedelta(seconds=1)  # 창은 안 밀린다


def test_실패는_실제로_누적된다(client, db, make_user):
    """세는 경로 자체를 진짜 로그인으로 확인한다(위 테스트들이 심는 상태가
    실제로 만들어지는 모양인지). bcrypt가 비싸서 횟수는 셋으로 줄인다."""
    user = make_user(role="writer", password="password123")

    for _ in range(3):
        assert client.post(
            "/api/auth/login", json={"email": user.email, "password": "wrong-password"}
        ).status_code == 401

    row = _failure_row(db, user)
    assert row is not None and row.fail_count == 3


def test_없는_계정의_실패는_아무_행도_안_만든다(client, db):
    """카운터는 계정에 딸린다(user_id가 FK). 주소를 지어내며 두드리는 것으로
    표를 부풀릴 수 없다 — 행 수는 계정 수를 못 넘고, 그래서 정리 작업이 필요 없다."""
    rows = select(func.count()).select_from(LoginFailure)
    before = db.scalar(rows)

    assert client.post(
        "/api/auth/login",
        json={"email": "ghost-account@test.com", "password": "password123"},
    ).status_code == 401

    assert db.scalar(rows) == before


def test_비번_재설정이_잠금을_푼다(client, db, make_user):
    """메일함을 쥔 사람에게는 빠져나올 문이 있어야 한다. 없으면 '남이 걸어둔 잠금'을
    주인이 15분 동안 못 푸는 상태가 된다."""
    user = make_user(role="writer", password="oldpassword1")
    _seed_failures(db, user, LOGIN_FAIL_MAX)
    token = create_email_token(user.id, purpose="reset", ver=user.token_version)

    assert client.post(
        "/api/auth/reset-password",
        json={"token": token, "new_password": "newpassword1"},
    ).status_code == 200

    assert _failure_row(db, user) is None
    assert client.post(
        "/api/auth/login", json={"email": user.email, "password": "newpassword1"}
    ).status_code == 200
