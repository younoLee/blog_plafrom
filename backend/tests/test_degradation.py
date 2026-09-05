"""의존성이 죽었을 때 우아하게 degrade 하는가 (2026-07-28 카오스 훈련의 회귀 테스트).

훈련에서 실측한 것들이다. 고쳐놓고 테스트를 안 붙이면 다음 리팩터에 조용히 되돌아간다.

훈련 전 상태:
  DB 정지    → 모든 경로가 500 `text/plain` ("Internal Server Error")
  S3 장애    → 업로드가 500 `text/plain` (botocore 예외가 그대로 터짐)
  업스트림   → 도달 불가·무응답 둘 다 "키/모델명 확인" 안내 (엉뚱한 곳을 고치라고 시킴)

핵심은 상태코드다. 프론트(api/http.ts)의 isAsleepStatus가 **502/503/504만**
'일시적 장애'로 안내하므로, 500이면 사용자는 그냥 빨간 에러를 본다.
"""

import httpx
import pytest
from botocore.exceptions import ClientError
from fastapi import HTTPException
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from app.core.database import get_db
from app.main import app
from app.routers.ai import _upstream_unreachable


@pytest.fixture
def db_down(client):
    """DB 접속이 끊긴 상태를 만든다(get_db가 OperationalError를 던지게)."""

    def boom():
        raise OperationalError("SELECT 1", {}, Exception("could not connect"))

    app.dependency_overrides[get_db] = boom
    yield client
    # conftest의 client 픽스처가 정리하지만, 다른 테스트로 새지 않게 여기서도 되돌린다
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def pool_exhausted(client):
    """커넥션 풀이 다 찬 상태(get_db 가 sqlalchemy TimeoutError 를 던진다).

    **DB 는 멀쩡하고 우리 쪽 커넥션이 없는 것**이라 위 db_down 과 다른 사건이다.
    main.py 가 두 핸들러를 따로 두는 이유가 거기 적혀 있는데(그 문서가 실측 함정 셋까지
    남겼다) 정작 이쪽은 시험이 0건이었다 — 핸들러를 하나로 합치는 리팩터가 오면
    `exc.orig` AttributeError 로 **다시 500 text/plain** 이 되는데 아무도 못 잡는다
    (09-04 검사 BQ-5).
    """

    def boom():
        raise PoolTimeoutError("QueuePool limit of size 10 overflow 10 reached")

    app.dependency_overrides[get_db] = boom
    yield client
    app.dependency_overrides.pop(get_db, None)


def test_풀_고갈도_503_json이다(pool_exhausted):
    r = pool_exhausted.get("/api/posts")
    assert r.status_code == 503
    assert r.headers["content-type"].startswith("application/json")


def test_풀_고갈은_더_빨리_다시_시도하라고_한다(pool_exhausted):
    """풀은 몇 초면 빈다. DB 정지(30초)와 같은 값을 주면 '언제 다시'가 뜻을 잃는다."""
    assert pool_exhausted.get("/api/posts").headers.get("retry-after") == "5"


def test_풀_고갈과_DB_정지는_다른_문장을_준다(pool_exhausted, client):
    """문구가 같아지면 사고 때 사람을 엉뚱한 곳으로 보낸다 — 하나는 DB 를 보라는 말이고
    다른 하나는 커넥션을 오래 쥔 요청을 보라는 말이다. 핸들러 병합 회귀를 여기서 잡는다."""
    pool_msg = pool_exhausted.get("/api/posts").json()["detail"]

    def boom():
        raise OperationalError("SELECT 1", {}, Exception("could not connect"))

    app.dependency_overrides[get_db] = boom
    try:
        db_msg = client.get("/api/posts").json()["detail"]
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert pool_msg != db_msg
    assert "몰려" in pool_msg


def test_db_outage_returns_503_json_not_500_text(db_down):
    r = db_down.get("/api/posts")
    assert r.status_code == 503, "500이면 프론트가 '일시적 장애'로 안내하지 못한다"
    assert r.headers["content-type"].startswith("application/json")
    assert "잠시 후" in r.json()["detail"]


def test_db_outage_tells_client_when_to_retry(db_down):
    # 사람뿐 아니라 기계(프록시·클라이언트)도 읽을 수 있어야 한다
    assert db_down.get("/api/posts").headers.get("retry-after") == "30"


def test_health_still_ok_during_db_outage(db_down):
    # 헬스체크는 DB를 안 본다 — 이건 의도된 것이다(liveness). DB가 죽었다고 컨테이너를
    # 재시작하면 복구는 안 되고 재시작 루프만 생긴다. 대신 /api/status가 database=down을
    # 보고하고 watch.sh가 그걸 읽는다.
    assert db_down.get("/api/health").status_code == 200


# 유효 PNG 매직바이트 — 내용 판별을 통과해야 S3 경로까지 간다
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def test_s3_failure_returns_503_not_500(client, make_user, auth_headers, monkeypatch):
    """S3가 거부하면 500이 아니라 503 + 안내."""
    import boto3

    import app.routers.uploads as up

    monkeypatch.setattr(up.settings, "s3_bucket", "bucket-that-fails")

    class FailingS3:
        def put_object(self, **kwargs):
            raise ClientError(
                {"Error": {"Code": "InvalidAccessKeyId", "Message": "bad key"}}, "PutObject"
            )

    monkeypatch.setattr(boto3, "client", lambda *a, **k: FailingS3())

    w = make_user(role="writer")
    r = client.post(
        "/api/upload", headers=auth_headers(w), files={"file": ("t.png", PNG, "image/png")}
    )
    assert r.status_code == 503, f"500이면 프론트가 안내를 못 한다 (받은 것: {r.status_code})"
    assert r.headers["content-type"].startswith("application/json")
    # 버킷명·권한 오류 같은 내부 사정은 밖으로 안 나가야 한다
    body = r.json()["detail"]
    assert "InvalidAccessKeyId" not in body and "bucket-that-fails" not in body


# ── 업스트림 분류: '못 닿았다'와 '거부당했다'를 갈라야 안내가 맞다 ──────────────
# 타입만으로 못 가른다 — 벤더 SDK가 httpx 예외를 자기 타입으로 감싸기 때문이다.
# 훈련 중 `except httpx.TimeoutException`만 걸었다가 하나도 안 걸리는 걸 재주입에서 발견했다.


def test_wrapped_timeout_is_treated_as_unreachable():
    try:
        try:
            raise httpx.ConnectTimeout("timed out")
        except httpx.ConnectTimeout as inner:
            raise RuntimeError("SDK가 감싼 예외") from inner
    except RuntimeError as e:
        assert _upstream_unreachable(e) is True


def test_deeply_wrapped_transport_error_is_unreachable():
    try:
        try:
            try:
                raise httpx.ConnectError("refused")
            except httpx.ConnectError as a:
                raise ValueError("1단계") from a
        except ValueError as b:
            raise RuntimeError("2단계") from b
    except RuntimeError as e:
        assert _upstream_unreachable(e) is True


def test_plain_error_is_not_unreachable():
    # 잘못된 키·없는 모델은 '거부당한 것'이라 안내가 달라야 한다
    assert _upstream_unreachable(HTTPException(status_code=401)) is False
    assert _upstream_unreachable(RuntimeError("model not found")) is False


def test_cyclic_cause_chain_terminates():
    # __cause__가 순환해도 무한루프에 빠지면 안 된다(요청 하나가 워커를 영원히 문다)
    a = RuntimeError("a")
    b = RuntimeError("b")
    a.__cause__ = b
    b.__cause__ = a
    assert _upstream_unreachable(a) is False
