"""요청 본문 크기 상한(BodySizeLimitMiddleware) 회귀 테스트.

2026-07-30 심층검사에서 실측한 것: 상한 검사가 **Content-Length만** 봐서, 같은 20MB를
`Transfer-Encoding: chunked`로 보내면 전부 앱까지 들어와 메모리에 버퍼링된 뒤 422가 났다.
무인증 라우트(로그인)에서도 되므로 t2.micro 메모리 고갈 경로였다.

여기서 못박는 계약은 둘이다:
  ① Content-Length가 없어도 상한을 넘으면 **앱에 닿기 전에** 끊긴다.
  ② 상한 이하 요청의 본문은 **조각 순서까지 그대로** 앱에 전달된다(replay).
②가 없으면 ①을 고치다가 정상 업로드를 조용히 망가뜨린다.

2026-09-02에 셋째가 붙었다:
  ③ 상한은 **경로마다 다르다**. 6MB는 이미지 업로드 때문에 잡은 값인데 그게 무인증
     JSON 경로(로그인·댓글·비밀번호 찾기)에도 그대로 걸려 있었다. 그 경로들의 본문은
     파싱 전에 통째로 메모리에 쌓이고 레이트리밋은 그 뒤에 돈다 → t2.micro 400m
     컨테이너에서 OOM 경로다. 이제 `/api/upload`만 6MB, 나머지는 512KB다.
     이 파일의 기존 테스트는 전 경로 6MB를 가정하고 쓰였으므로, 상수를 그대로 쓰되
     그 상수의 값이 512KB로 바뀐 것을 따라간다(아래 주석 참고).

HTTP 레벨(TestClient)은 본문을 한 덩어리로 합쳐 넘기므로 조각 경계를 재현하지 못한다.
그래서 스트리밍 동작은 미들웨어를 ASGI 레벨에서 직접 호출해 검증한다.
경로별 상한도 마찬가지다 — 조각난 스트림에서 어느 상한이 골라지는지는 ASGI 레벨에서 본다.
"""
import asyncio
import json

import app.main as main_module
from app.main import (
    MAX_BODY_BYTES,
    MAX_TRACKED_CHUNKS,
    MAX_UPLOAD_BODY_BYTES,
    UPLOAD_PATH,
    BodySizeLimitMiddleware,
)

# 유효 PNG 매직바이트(test_uploads.py와 같은 것). 업로드 경로를 실제로 태우는 데 쓴다.
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
ONE_MB = 1024 * 1024

# ── HTTP 레벨: 실제 앱을 통과시켜 우회가 막혔는지 본다 ──────────────────────


def _over_limit_chunks(limit: int = MAX_BODY_BYTES):
    """상한을 넘기는 본문. content=제너레이터면 httpx가 Content-Length를 안 붙이고
    Transfer-Encoding: chunked로 보낸다 = 어제 우회에 쓰인 그 모양.

    limit을 인자로 받게 바꿨다(2026-09-02) — 경로마다 상한이 달라져서, '넘긴다'가
    어느 상한 기준인지 호출부가 말해야 한다."""
    sent = 0
    while sent <= limit:
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


# ── 경로별 상한 (2026-09-02) ──────────────────────────────────────────────
#
# 이 셋이 못박는 것: 업로드 때문에 넓힌 문이 **업로드 경로에만** 넓다.
# 예전엔 셋 다 6MB 하나로 통과했으므로, 여기가 회귀하면 OOM 경로가 그대로 돌아온다.


def test_json_route_blocks_1mb_body(client):
    """무인증 JSON 경로는 1MB에서 막힌다. 이게 이번 변경의 본체다.

    1MB는 정상 요청 중 가장 큰 것(POST /api/posts, 본문 50,000자 ≈ 150~205KB)보다
    한참 위다 — 정상 트래픽을 자르지 않으면서 6MB 노출만 없앤 자리를 고른 것이다.
    """
    r = client.post(
        "/api/auth/login",
        content=b"a" * ONE_MB,
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 413


def test_upload_route_still_accepts_1mb_body(client):
    """같은 1MB라도 `/api/upload`는 막히지 않는다.

    401(= 인증에서 걸림)은 **본문이 미들웨어를 통과해 앱까지 갔다**는 뜻이다.
    413이 나오면 상한을 경로와 무관하게 좁힌 것이고, 그 순간 5MB 이미지 업로드가 죽는다.
    (test_uploads.py의 test_upload_requires_auth와 같은 모양에 크기만 키웠다)

    2026-09-05: 인증 헤더를 붙인다. 큰 상한은 이제 '인증 헤더가 붙은 요청'에만
    주어진다(SEC-01). 토큰은 가짜라 결말은 여전히 401이고, 그게 곧 본문이 앱까지
    갔다는 증거다. 헤더 없이 보내는 경우는 바로 아래 시험이 따로 잠근다.
    """
    r = client.post(
        "/api/upload",
        files={"file": ("big.png", PNG + b"0" * ONE_MB, "image/png")},
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert r.status_code == 401


def test_upload_route_denies_big_body_without_auth_header(client):
    """인증 헤더가 없으면 업로드 경로도 큰 본문을 안 받는다.

    ⚠️ **2026-09-05까지 받았다.** 상한 판정이 경로 하나뿐이라, 로그인하지 않은 요청도
    6MB를 얻었다. 업로드는 require_writer로 잠겨 있어 결말은 401인데, FastAPI는 본문을
    **다 읽은 뒤에** 의존성을 풀고(routing.py의 `await request.form()`이 먼저다)
    엔드포인트 안의 레이트리밋도 그 경로에서는 안 돈다. 즉 거절될 요청 하나가 6MB를
    먼저 먹었다(2026-09-04 검사 SEC-01).

    413이 맞는 답이다 — 읽지 않고 끊는다.
    """
    r = client.post(
        "/api/upload",
        files={"file": ("big.png", PNG + b"0" * ONE_MB, "image/png")},
    )
    assert r.status_code == 413


def test_upload_route_blocks_over_its_own_limit(client):
    """업로드 경로에도 상한은 있다 — 6MB를 넘으면 여전히 413.

    인증 헤더를 붙여야 **업로드 상한**을 시험하는 게 된다. 안 붙이면 작은 상한에
    걸려서 413이 나오고, 그러면 이 시험은 6MB 상한이 사라져도 통과한다(2026-09-05).
    """
    r = client.post(
        "/api/upload",
        content=b"a" * (MAX_UPLOAD_BODY_BYTES + 1),
        headers={
            "Content-Type": "application/octet-stream",
            "Authorization": "Bearer not-a-real-token",
        },
    )
    assert r.status_code == 413


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


def _run(
    messages: list[dict],
    max_bytes: int = 64,
    path: str = "/x",
    upload_max_bytes: int | None = None,
    query_string: bytes = b"",
    authorized: bool = True,
    spool_max_bytes: int | None = None,
):
    """Content-Length 없는 http scope로 미들웨어를 돌리고
    (하위앱, 나간 응답들, receive 호출 횟수)를 돌려준다.

    path·upload_max_bytes·query_string은 2026-09-02에 붙였다. 경로별 상한이
    **chunked 경로에서도** 도는지 보려면 scope의 path를 갈아끼울 수 있어야 한다.

    authorized는 2026-09-05에 붙였다. 업로드 상한은 이제 인증 헤더가 붙은 요청에만
    주어지므로(SEC-01), 그 갈래를 시험하려면 헤더를 넣고 뺄 수 있어야 한다.
    기본값을 True로 둔 이유는 기존 시험들이 전부 '정상적인 업로드'를 뜻하기 때문이다.

    spool_max_bytes는 2026-09-06에 붙였다. 큰 본문이 메모리가 아니라 디스크로 가는지를
    보려면 문턱을 시험이 정할 수 있어야 한다(실제 값 512KB로는 시험이 512KB를 만든다)."""
    downstream = _Downstream()
    kwargs = {} if spool_max_bytes is None else {"spool_max_bytes": spool_max_bytes}
    mw = BodySizeLimitMiddleware(
        downstream, max_bytes=max_bytes, upload_max_bytes=upload_max_bytes, **kwargs
    )
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "path": path,
        "query_string": query_string,
        # Content-Length 없음 → 스트림 검사 경로.
        # authorization 은 값을 검증하지 않는다(미들웨어도 존재 여부만 본다).
        "headers": [(b"authorization", b"Bearer t")] if authorized else [],
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


def _chunks(total: int, piece: int = 40) -> list[dict]:
    """total 바이트를 piece 크기 조각으로 쪼갠 http.request 메시지들."""
    parts = [piece] * (total // piece) + ([total % piece] if total % piece else [])
    return [
        {"type": "http.request", "body": b"a" * n, "more_body": i < len(parts) - 1}
        for i, n in enumerate(parts)
    ]


def test_chunked_stream_uses_the_upload_limit_on_the_upload_path():
    """chunked 경로도 경로별 상한을 따른다 — 같은 본문, 다른 경로, 다른 결과.

    Content-Length 경로만 고치고 여기를 안 고치면 넓은 쪽이 그대로 우회로가 된다
    (07-30에 배운 그 모양이 정확히 이것이다).
    """
    messages = _chunks(200)

    on_upload, sent_up, _ = _run(messages, max_bytes=64, path=UPLOAD_PATH, upload_max_bytes=256)
    assert on_upload.body == b"a" * 200
    assert _status(sent_up) == 200

    on_json, sent_json, _ = _run(
        _chunks(200), max_bytes=64, path="/api/auth/login", upload_max_bytes=256
    )
    assert not on_json.called
    assert _status(sent_json) == 413


def test_chunked_upload_without_auth_header_gets_the_small_limit():
    """chunked 갈래에서도 인증 헤더가 없으면 작은 상한이다.

    Content-Length 쪽만 고치고 여기를 안 고치면 넓은 쪽이 그대로 우회로가 된다.
    이 파일이 09-02에 같은 이유로 배운 것이라(위 test_chunked_stream_... 참고)
    같은 모양으로 한 번 더 잠근다.

    무인증 요청이 **버퍼링되기 전에** 끊기는지가 요점이다 — 앱까지 안 가야 한다.
    """
    on_upload, sent, _ = _run(
        _chunks(200),
        max_bytes=64,
        path=UPLOAD_PATH,
        upload_max_bytes=256,
        authorized=False,
    )
    assert not on_upload.called
    assert _status(sent) == 413


def test_upload_limit_is_matched_exactly_not_by_prefix():
    """`/api/uploadsomething`은 업로드가 아니다.

    접두사 매칭으로 짰다면 이 경로가 6MB를 얻는다. 무인증 경로 하나만 잘못 넓혀도
    이번에 없앤 OOM 경로가 그대로 되살아나므로, 여기는 '정확히 같은가'여야 한다.
    """
    downstream, sent, _ = _run(
        _chunks(200), max_bytes=64, path=UPLOAD_PATH + "something", upload_max_bytes=256
    )
    assert not downstream.called
    assert _status(sent) == 413


def test_trailing_slash_and_query_still_count_as_upload():
    """후행 슬래시·쿼리스트링이 붙어도 업로드는 업로드다.

    쿼리스트링은 scope의 path에 안 들어가므로(따로 query_string에 있다) 원래 영향이
    없어야 하는데, '없어야 한다'와 '없다'는 다르다 — 그래서 여기서 한 번 확인한다.
    """
    for path, qs in ((UPLOAD_PATH + "/", b""), (UPLOAD_PATH, b"x=1"), (UPLOAD_PATH + "/", b"x=1")):
        downstream, sent, _ = _run(
            _chunks(200),
            max_bytes=64,
            path=path,
            upload_max_bytes=256,
            query_string=qs,
        )
        assert downstream.body == b"a" * 200, path
        assert _status(sent) == 200, path


def test_disconnect_before_body_is_passed_through():
    """클라가 본문 전에 끊으면 http.disconnect가 그대로 하위 앱에 전달돼야 한다.
    삼켜버리면 하위 앱이 오지 않을 본문을 영원히 기다린다."""
    messages = [{"type": "http.disconnect"}]
    downstream, sent, _ = _run(messages, max_bytes=64)

    assert downstream.called
    assert downstream.chunks == []
    assert _status(sent) == 200


# ── 큰 본문은 메모리가 아니라 디스크로 (2026-09-06, SEC-01 잔여) ────────────
#
# 09-05에 넣은 '인증 헤더가 없으면 업로드 상한을 안 준다'는 `Authorization: Bearer x`
# 한 줄이면 도로 뚫린다 — 미들웨어는 라우팅 전이라 토큰을 검증할 수단이 없다.
# 그래서 진짜 상한은 '받아두는 곳'에 있다. 상한만큼(6MB)을 파이썬 리스트에 담으면
# 위조 헤더 하나로 6MB를 프로세스 메모리에 밀어넣을 수 있고, t2.micro 400m 컨테이너에서
# 그런 연결 수십 개면 OOM이다(2026-09-04 검사 SEC-01의 남은 절반).
#
# 여기서 못박는 계약 셋:
#   ④ 문턱을 넘는 본문은 **디스크로 넘어간다**(메모리에 남는 몫이 문턱으로 묶인다).
#   ⑤ 그렇게 받아둔 본문도 앱에는 **온전히** 전달된다 — 디스크를 경유해도 내용이 같다.
#   ⑥ 임시파일은 요청이 끝나면 **지워진다**(안 지우면 고장이 메모리에서 디스크로 옮겨간 것뿐).


def _spy_buffers(monkeypatch) -> list:
    """미들웨어가 만든 스풀 파일을 붙잡아 두는 감시자.

    '디스크로 넘어갔는가'는 밖에서 볼 수 없는 사실이라 객체를 직접 봐야 한다.
    SpooledTemporaryFile은 넘어간 뒤에 `_rolled`가 True가 된다(CPython 3.x 공통).
    """
    made = []
    real = main_module.SpooledTemporaryFile

    def spy(*args, **kwargs):
        f = real(*args, **kwargs)
        made.append(f)
        return f

    monkeypatch.setattr(main_module, "SpooledTemporaryFile", spy)
    return made


def test_body_over_the_spool_threshold_goes_to_disk(monkeypatch):
    """문턱(여기선 64B)을 넘는 본문은 메모리에 계속 쌓이지 않는다.

    ④와 ⑤를 한 번에 본다 — 디스크로 넘어갔고(rolled), 앱이 받은 내용은 그대로다.
    """
    made = _spy_buffers(monkeypatch)
    downstream, sent, _ = _run(_chunks(200), max_bytes=256, spool_max_bytes=64)

    assert made and made[0]._rolled  # 메모리에 200바이트를 들고 있지 않았다
    assert downstream.body == b"a" * 200
    assert _status(sent) == 200


def test_body_under_the_spool_threshold_never_touches_disk(monkeypatch):
    """문턱 아래 본문은 디스크에 안 간다.

    실제 문턱은 무인증 JSON 경로의 상한과 같은 512KB다. 즉 로그인·댓글 같은 평범한
    요청이 파일을 만들면 안 된다 — 여기가 회귀하면 요청마다 임시파일이 생긴다.
    """
    made = _spy_buffers(monkeypatch)
    downstream, sent, _ = _run(_chunks(40), max_bytes=256, spool_max_bytes=1024)

    assert made and not made[0]._rolled
    assert downstream.body == b"a" * 40
    assert _status(sent) == 200


def test_spool_file_is_closed_when_the_request_ends(monkeypatch):
    """임시파일은 요청이 끝나면 지워진다(close = 삭제).

    이걸 빠뜨리면 고장이 사라진 게 아니라 메모리에서 디스크로 자리를 옮긴 것이 된다.
    """
    made = _spy_buffers(monkeypatch)
    _run(_chunks(200), max_bytes=256, spool_max_bytes=64)

    assert made[0].closed


def test_spool_file_is_closed_even_if_the_app_raises(monkeypatch):
    """앱이 터져도 임시파일은 남지 않는다."""
    made = _spy_buffers(monkeypatch)

    class _Boom:
        async def __call__(self, scope, receive, send):
            raise RuntimeError("boom")

    mw = BodySizeLimitMiddleware(_Boom(), max_bytes=256, spool_max_bytes=64)
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "path": "/x",
        "query_string": b"",
        "headers": [],
    }
    queue = _chunks(200)

    async def receive():
        return queue.pop(0)

    async def send(message):
        pass

    try:
        asyncio.run(mw(scope, receive, send))
    except RuntimeError:
        pass
    else:  # pragma: no cover - 예외가 안 나면 시험 전제가 깨진 것이다
        raise AssertionError("하위 앱의 예외가 삼켜졌다")

    assert made[0].closed


def test_many_tiny_chunks_do_not_keep_a_boundary_per_chunk():
    """1바이트짜리 조각 수천 개로 와도 경계 목록이 본문보다 커지지 않는다.

    조각 경계를 전부 기억하면(리스트 원소 하나에 int 하나) 본문을 디스크로 옮긴 의미가
    사라진다 — 6MB를 1바이트씩 보내면 int 600만 개가 메모리에 남기 때문이다.
    MAX_TRACKED_CHUNKS를 넘으면 경계를 버리고 고정 크기로 되돌려주고, **내용은 같다**.
    ASGI는 조각 경계를 약속하지 않으므로 받는 쪽은 이 차이를 못 느낀다.
    """
    n = MAX_TRACKED_CHUNKS + 50
    messages = [
        {"type": "http.request", "body": b"a", "more_body": i < n - 1} for i in range(n)
    ]
    downstream, sent, _ = _run(messages, max_bytes=n * 2)

    assert downstream.body == b"a" * n  # 내용은 온전하다
    assert len(downstream.chunks) < n  # 조각은 합쳐져서 나갔다
    assert _status(sent) == 200


def test_disconnect_after_partial_body_is_delivered_after_that_body():
    """본문 일부만 오고 끊긴 경우, 앱은 받은 만큼을 먼저 받고 그 다음 disconnect를 본다.

    되돌려줄 때 마지막 본문 조각의 more_body를 False로 만들어버리면 앱이 disconnect를
    영영 못 보고 '정상적으로 끝난 짧은 본문'으로 오해한다.
    """
    messages = [
        {"type": "http.request", "body": b"one", "more_body": True},
        {"type": "http.request", "body": b"two", "more_body": True},
        {"type": "http.disconnect"},
    ]
    downstream, sent, _ = _run(messages, max_bytes=64)

    assert downstream.chunks == [b"one", b"two"]
    assert _status(sent) == 200


def test_chunked_multipart_upload_survives_the_round_trip_through_disk(client):
    """HTTP 레벨: 문턱을 넘는 chunked 업로드가 디스크를 거쳐도 그대로 파싱된다.

    401이 나온다는 건 multipart가 **끝까지 파싱됐다**는 뜻이다 — FastAPI는 본문을
    다 읽은 뒤에 의존성을 풀기 때문에(`await request.form()`이 먼저다) 되돌려주기가
    한 바이트라도 어긋나면 401이 아니라 422가 난다.
    """
    boundary = "----blogtestboundary"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="big.png"\r\n'
        "Content-Type: image/png\r\n\r\n"
    ).encode()
    body += PNG + b"0" * ONE_MB + f"\r\n--{boundary}--\r\n".encode()

    def gen():
        for i in range(0, len(body), 64 * 1024):
            yield body[i : i + 64 * 1024]

    r = client.post(
        "/api/upload",
        content=gen(),  # 제너레이터 → Content-Length 없이 chunked
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Authorization": "Bearer not-a-real-token",
        },
    )
    assert r.status_code == 401
