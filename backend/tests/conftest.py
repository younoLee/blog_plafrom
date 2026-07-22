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
              is_pro=False, verified=True):
        u = User(
            email=email or f"{role}-{uuid.uuid4().hex[:8]}@test.com",
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


@pytest.fixture
def sent_mail(no_smtp):
    """가로챈 메일 목록. 필요하면 테스트에서 발송 여부·수신자를 확인한다."""
    return no_smtp
