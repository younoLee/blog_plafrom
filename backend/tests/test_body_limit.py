"""요청 본문 크기 상한(BodySizeLimitMiddleware) 회귀 테스트.

2026-07-30 심층검사에서 실측한 것: 상한 검사가 **Content-Length만** 봐서, 같은 20MB를
`Transfer-Encoding: chunked`로 보내면 전부 앱까지 들어와 메모리에 버퍼링된 뒤 422가 났다.
무인증 라우트(로그인)에서도 되므로 t2.micro 메모리 고갈 경로였다.

여기서 못박는 계약은 둘이다:
  ① Content-Length가 없어도 상한을 넘으면 **앱에 닿기 전에** 끊긴다.
  ② 상한 이하 요청의 본문은 **조각 순서까지 그대로** 앱에 전달된다(replay).
②가 없으면 ①을 고치다가 정상 업로드를 조용히 망가뜨린다.

HTTP 레벨(TestClient)은 본문을 한 덩어리로 합쳐 넘기므로 조각 경계를 재현하지 못한다.
그래서 스트리밍 동작은 미들웨어를 ASGI 레벨에서 직접 호출해 검증한다.
"""
import asyncio
import json

from app.main import MAX_BODY_BYTES, BodySizeLimitMiddleware

# ── HTTP 레벨: 실제 앱을 통과시켜 우회가 막혔는지 본다 ──────────────────────


def _over_limit_chunks():
    """상한을 넘기는 본문. content=제너레이터면 httpx가 Content-Length를 안 붙이고
    Transfer-Encoding: chunked로 보낸다 = 어제 우회에 쓰인 그 모양."""
    sent = 0
    while sent <= MAX_BODY_BYTES:
        yield b"a" * (256 * 1024)
        sent += 256 * 1024


def test_chunked_body_over_limit_is_blocked(client):
    # 수정 전: 본문을 전부 버퍼링한 뒤 JSON 파싱까지 가서 422가 났다(= 우회 성공).
    r = client.post(
        "/api/auth/login",
        content=_over_limit_chunks(),
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 413


def test_content_length_body_over_limit_is_blocked(client):
    # 대조군: 예전 코드도 막던 경로. 고치면서 깨지지 않았는지 확인한다.
    r = client.post(
        "/api/auth/login",
        content=b"a" * (MAX_BODY_BYTES + 1),
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 413


def test_chunked_body_under_limit_reaches_app_intact(client):
    """상한 이하 chunked 요청은 앱이 본문을 온전히 받아야 한다.

    401(= 자격 불일치)이 나온다는 건 JSON이 끝까지 파싱됐다는 뜻이다.
    replay가 깨지면 여기서 422가 난다.
    """
    body = json.dumps({"email": "nobody@example.com", "password": "whatever12"}).encode()

    def gen():
        yield body

    r = client.post(
        "/api/auth/login", content=gen(), headers={"Content-Type": "application/json"}
    )
    assert r.status_code == 401


# ── ASGI 레벨: 조각난 스트림에서의 동작 ────────────────────────────────────


class _Downstream:
    """받은 본문을 조각 단위로 기록하는 하위 ASGI 앱."""

    def __init__(self):
        self.chunks: list[bytes] = []
        self.called = False

    async def __call__(self, scope, receive, send):
        self.called = True
        while True:
            m = await receive()
            if m["type"] != "http.request":
                break
            self.chunks.append(m.get("body", b""))
            if not m.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    @property
    def body(self) -> bytes:
        return b"".join(self.chunks)


def _run(messages: list[dict], max_bytes: int = 64):
    """Content-Length 없는 http scope로 미들웨어를 돌리고
    (하위앱, 나간 응답들, receive 호출 횟수)를 돌려준다."""
    downstream = _Downstream()
    mw = BodySizeLimitMiddleware(downstream, max_bytes=max_bytes)
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "path": "/x",
        "query_string": b"",
        "headers": [],  # Content-Length 없음 → 스트림 검사 경로
    }
    queue = list(messages)
    calls = {"n": 0}
    sent: list[dict] = []

    async def receive():
        calls["n"] += 1
        return queue.pop(0)

    async def send(message):
        sent.append(message)

    asyncio.run(mw(scope, receive, send))
    return downstream, sent, calls["n"]


def _status(sent: list[dict]) -> int:
    return next(m["status"] for m in sent if m["type"] == "http.response.start")


def test_multi_chunk_body_is_replayed_in_order():
    """조각이 여러 개여도 앱은 같은 순서·같은 내용을 받아야 한다."""
    parts = [b"one", b"two", b"three"]
    messages = [
        {"type": "http.request", "body": p, "more_body": i < len(parts) - 1}
        for i, p in enumerate(parts)
    ]
    downstream, sent, _ = _run(messages, max_bytes=64)

    assert downstream.called
    assert downstream.chunks == parts  # 합계뿐 아니라 경계까지 보존
    assert _status(sent) == 200


def test_stream_is_cut_as_soon_as_limit_is_passed():
    """상한을 넘는 순간 끊는다 — 하위 앱은 호출조차 되지 않고,
    남은 조각은 읽지 않는다(그게 메모리를 아끼는 지점이다)."""
    messages = [
        {"type": "http.request", "body": b"a" * 40, "more_body": True},
        {"type": "http.request", "body": b"b" * 40, "more_body": True},  # 여기서 80 > 64
        {"type": "http.request", "body": b"c" * 40, "more_body": False},  # 안 읽혀야 함
    ]
    downstream, sent, receive_calls = _run(messages, max_bytes=64)

    assert not downstream.called  # 본문이 앱에 닿지 않았다
    assert _status(sent) == 413
    assert receive_calls == 2  # 세 번째 조각은 읽지 않았다


def test_body_exactly_at_limit_is_allowed():
    """경계값: 상한과 '같은' 크기는 통과한다(초과만 막는다)."""
    messages = [{"type": "http.request", "body": b"a" * 64, "more_body": False}]
    downstream, sent, _ = _run(messages, max_bytes=64)

    assert downstream.body == b"a" * 64
    assert _status(sent) == 200


def test_disconnect_before_body_is_passed_through():
    """클라가 본문 전에 끊으면 http.disconnect가 그대로 하위 앱에 전달돼야 한다.
    삼켜버리면 하위 앱이 오지 않을 본문을 영원히 기다린다."""
    messages = [{"type": "http.disconnect"}]
    downstream, sent, _ = _run(messages, max_bytes=64)

    assert downstream.called
    assert downstream.chunks == []
    assert _status(sent) == 200
