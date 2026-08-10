"""pytest 공통 픽스처 — 실제 Postgres 대상 통합 테스트.

왜 Postgres인가: posts.tags가 ARRAY(String)이고 검색이 pg_trgm(GIN) 인덱스라
SQLite로는 create_all조차 안 된다. 그래서 테스트도 프로드와 같은 Postgres를 쓴다
(로컬은 blog_test DB, CI는 postgres 서비스 컨테이너).

격리: 테스트마다 커넥션 하나에서 트랜잭션을 열고 끝나면 통째로 롤백한다. 앱 코드가
내부에서 commit()해도 savepoint로 잡혀 롤백되므로(join_transaction_mode) 테스트 간
오염이 없다.
"""
import os
import uuid

# ── 앱을 import 하기 전에 환경을 먼저 세팅한다 (config.Settings가 import 시점에 읽음) ──
os.environ.setdefault(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/blog_test"
)
# main.py lifespan의 SECRET_KEY 가드(≥16자, 기본값 금지)를 통과할 강한 값
os.environ.setdefault("SECRET_KEY", "test-secret-key-0123456789abcdef")

# StaticFiles(directory="uploads") 마운트가 import 시점에 폴더 존재를 요구 → 없으면 만든다
os.makedirs("uploads", exist_ok=True)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import Base, get_db
from app.core.ratelimit import limiter
from app.core.security import create_access_token, hash_password
from app.main import app  # 라우터 import가 전 모델을 Base.metadata에 등록시킨다
from app.models.user import User


def _ensure_database(url: str) -> None:
    """대상 테스트 DB가 없으면 만든다(서버 기본 postgres DB에 붙어 CREATE DATABASE)."""
    base, _, dbname = url.rpartition("/")
    admin = create_engine(f"{base}/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": dbname}
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{dbname}"'))
    admin.dispose()


_ensure_database(settings.database_url)
engine = create_engine(settings.database_url)

# 스키마 준비: pg_trgm 확장(모델의 gin_trgm_ops 인덱스가 요구) → 전 테이블 생성
with engine.connect() as conn:
    conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    conn.commit()
Base.metadata.create_all(bind=engine)


def _assert_schema_fresh(eng) -> None:
    """모델이 요구하는 테이블·컬럼·인덱스가 **실제로 DB에 있는지** 확인한다.

    `create_all`은 **이미 있는 테이블은 통째로 건너뛴다.** 컬럼이나 인덱스를
    새로 추가해도 기존 테이블에는 반영되지 않는다. CI는 매번 새 Postgres
    컨테이너라 이 구멍을 안 밟지만, 로컬은 `blog_test`가 계속 남아 있어서
    **옛 스키마 위에서 초록이 난다.** 2026-08-09에 실제로 겪었다:
    lower(email) 유니크 인덱스를 넣고 테스트를 짰는데, 인덱스가 안 생긴 채
    "중복이 안 막힌다"로 실패했다. 코드는 맞았고 DB가 낡았던 것이다.

    반대 방향이었으면 더 나빴다 — 낡은 DB에 우연히 맞는 테스트였다면
    **없는 방어를 있다고 믿은 채** CI까지 초록이었을 것이다.
    (개발일지 #26의 "신호가 어디까지 봤는가"가 그대로 여기다)

    **컬럼을 함께 본다.** 처음 쓸 때는 테이블·인덱스 *이름*만 비교했는데, 그러면
    가장 흔한 변경인 '컬럼 추가'가 그대로 통과한다(테이블도 인덱스도 안 늘어나니까).
    그 경우 이 함수는 초록을 내고, 정작 실패는 한참 뒤 관계없는 픽스처에서
    `UndefinedColumn`으로 터진다 — 이 가드가 없애겠다고 만든 바로 그 불친절한 실패다.
    자기가 못 보는 범위를 자기 설명이 덮고 있었던 셈이라, 2026-08-09 코드검사가 잡았다.

    **여전히 안 보는 것**(알고 두는 것): 컬럼의 타입·nullable·기본값, 유니크/체크
    제약, 외래키. 이름이 같은데 정의만 바뀌는 변경은 여기서 안 걸린다. 그 경우까지
    보려면 사실상 마이그레이션을 돌려야 하고, 그건 이 파일의 몫이 아니다
    (CI의 '빈 DB에 upgrade head' 잡이 그걸 본다).
    """
    from sqlalchemy import inspect

    insp = inspect(eng)
    have_tables = set(insp.get_table_names())
    missing = [t for t in Base.metadata.tables if t not in have_tables]
    for name, table in Base.metadata.tables.items():
        if name in have_tables:
            have_cols = {c["name"] for c in insp.get_columns(name)}
            missing += [f"{name}.{c}" for c in table.columns.keys() if c not in have_cols]
            have = {i["name"] for i in insp.get_indexes(name)}
            missing += [f"{name}.{ix.name}" for ix in table.indexes if ix.name not in have]
    if missing:
        raise RuntimeError(
            "테스트 DB 스키마가 모델보다 낡았습니다 — 없는 것: "
            f"{', '.join(sorted(missing))}\n"
            "create_all은 기존 테이블을 건드리지 않습니다. 테스트 DB를 지우고 다시 도세요:\n"
            "  docker compose exec -T db psql -U postgres -c "
            "'DROP DATABASE IF EXISTS blog_test WITH (FORCE)'"
        )


_assert_schema_fresh(engine)

# 레이트리밋은 테스트에서 끈다 (login 10/min·register 5/hour 등이 반복 호출과 충돌)
limiter.enabled = False


@pytest.fixture
def db():
    """테스트 1개당 트랜잭션 1개 → 끝나면 롤백(격리)."""
    connection = engine.connect()
    trans = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        trans.rollback()
        connection.close()


@pytest.fixture
def client(db):
    """get_db를 위 트랜잭션 세션으로 갈아끼운 TestClient.
    lifespan(백그라운드 스레드·SECRET_KEY 가드)은 일부러 안 돌린다(with 미사용)."""

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    c = TestClient(app)
    try:
        yield c
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def make_user(db):
    """유저를 DB에 직접 시드(가입·이메일인증 흐름 우회). role/is_pro 지정 가능."""

    def _make(role="writer", *, email=None, password="password123",
              is_pro=False, verified=True, display_name=None):
        u = User(
            email=email or f"{role}-{uuid.uuid4().hex[:8]}@test.com",
            display_name=display_name,
            hashed_password=hash_password(password),
            role=role,
            email_verified=verified,
            is_pro=is_pro,
        )
        db.add(u)
        db.commit()
        db.refresh(u)
        return u

    return _make


@pytest.fixture
def auth_headers():
    """유저 → Authorization 헤더 (로그인 엔드포인트 안 거치고 토큰 직접 발급)."""

    def _headers(user: User) -> dict:
        token = create_access_token(user.id, user.token_version)
        return {"Authorization": f"Bearer {token}"}

    return _headers


# ── 메일: 실제 SMTP에 붙지 않게 가로챈다 ─────────────────────────────────────
@pytest.fixture(autouse=True)
def no_smtp(monkeypatch):
    """테스트가 SMTP 서버에 의존하지 않게 만든다.

    왜 필요한가 (2026-07-22에 CI가 이것 때문에 하루 종일 빨간불이었다):
    가입·비번재설정 라우터가 `BackgroundTasks`로 메일을 보낸다. TestClient는
    백그라운드 작업을 응답 뒤에 **동기로** 실행하는데, starlette 1.3으로 올린 뒤부터
    그 안에서 난 예외가 테스트까지 전파된다. 로컬에는 mailpit이 떠 있어 조용히
    성공하지만 CI에는 메일 서버가 없어 `ConnectionRefusedError`로 3개가 깨졌다.
    즉 **환경에 따라 결과가 갈리는 테스트**였고, 그게 로컬에서만 초록인 이유였다.

    메일 서버를 CI에 띄우는 대신 SMTP만 가로챈다. 메시지 조립·제목 CRLF 제거·
    HTML 이스케이프 같은 코드 경로는 그대로 지나가므로 검증 범위가 줄지 않는다.
    보낸 메시지는 `sent_mail`로 확인할 수 있다.
    """
    import smtplib

    sent: list = []

    class _FakeSMTP:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, *a, **kw):
            pass

        def login(self, *a, **kw):
            pass

        def send_message(self, msg, *a, **kw):
            sent.append(msg)

        def quit(self):
            pass

    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    return sent


# ── 가입 게이트: 테스트 기본은 '열림' ────────────────────────────────────────
@pytest.fixture(autouse=True)
def open_signup(monkeypatch):
    """운영 기본은 초대제(allow_signup=False)로 닫혀 있지만, register 플로우를 검증하는
    기존 테스트들은 '열린' 상태를 전제한다. 그래서 테스트 기본을 열림으로 둔다.
    닫힘(403) 동작은 test_auth_security.py가 이 값을 되돌려 따로 검증한다."""
    monkeypatch.setattr(settings, "allow_signup", True)


# ── SES 조회: 네트워크로 안 나간다 ──────────────────────────────────────────
@pytest.fixture(autouse=True)
def no_ses(monkeypatch):
    """초대 발급이 부르는 SES 조회를 가로챈다.

    routers/admin.py의 create_invite가 recipient_status()를 부르는데, 그건 boto3로
    **실제 AWS에 나간다.** 자격증명이 없으면 예외로 끝나긴 하지만 그 전에
    자격증명 탐색(환경변수 → 공유파일 → IMDS 169.254.169.254)을 돌고, IMDS가
    닿지 않는 곳에서는 연결 타임아웃까지 기다린다. 초대를 만드는 테스트가 수십 개라
    그만큼 곱해진다 — 로컬 전체 스위트가 74초에서 152초로 늘었고, CI도 같은 이유로
    흔들린다. 무엇보다 **테스트가 바깥 네트워크에 의존하면 안 된다.**

    기본값은 '모름'(None) — 프로덕션에서 권한이 없을 때와 같은 상태다. 특정 값이
    필요한 테스트는 admin 라우터의 이름을 직접 갈아끼운다(test_invites.py 참고).
    no_smtp·no_push와 같은 방침이다."""
    from app.routers import admin as admin_router

    monkeypatch.setattr(
        admin_router, "recipient_status", lambda _e: {"sandbox": None, "verified": None}
    )


# ── 푸시: 기본은 '꺼짐' ──────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def no_push(monkeypatch):
    """VAPID 키를 비워 푸시를 전 테스트에서 끈다 (no_smtp와 같은 이유).

    켜져 있으면 글 발행 테스트가 실제로 바깥을 때린다. routers/posts.py가
    notify_new_post_push를 BackgroundTask로 걸고 TestClient는 그걸 **동기로**
    실행하므로, .env에 키가 있는 개발자·CI에서는 fcm.googleapis.com으로 진짜
    HTTPS 요청이 나간다(기기당 최대 10초). 게다가 그 함수는 자체 SessionLocal을
    열어 테스트 트랜잭션 **바깥**에서 DELETE를 하므로 롤백되지도 않는다.

    이미 test_push.py가 같은 함정을 겪고 그 파일 안에서만 막아뒀는데, 나머지
    스위트는 무방비였다. 2026-07-22에 SMTP로 하루 겪은 일과 같은 모양이라
    같은 자리에서 같은 방식으로 막는다. 켜고 싶은 테스트는 push_on을 쓴다."""
    monkeypatch.setattr(settings, "vapid_public_key", "")
    monkeypatch.setattr(settings, "vapid_private_key", "")


@pytest.fixture
def sent_mail(no_smtp):
    """가로챈 메일 목록. 필요하면 테스트에서 발송 여부·수신자를 확인한다."""
    return no_smtp
