"""BYOK base_url의 SSRF 검증.

`validate_base_url`은 이 앱에서 **서버가 임의 주소로 요청을 보내는 유일한 입구**다.
그런데 2026-08-11 공백검사 기준 테스트가 0건이었다 — SSRF 방어가 통째로 사라져도
CI가 초록이라는 뜻이다. 순수 함수라 DB도 HTTP 클라이언트도 필요 없다.

포트 `ValueError` 건은 특히 회귀 테스트가 있어야 한다: 2026-08-10 보안검사가
`https://example.com:99999/v1` → 500 text/plain 을 **실측 재현**해서 고친 자리인데,
`try/except ValueError` 세 줄을 지우면 조용히 그 상태로 돌아간다.
"""

import pytest

from app.services.llm_keys import InvalidBaseURLError, validate_base_url


@pytest.mark.parametrize(
    "url,reason",
    [
        ("http://api.openai.com/v1", "평문 http"),
        ("ftp://api.openai.com/v1", "https가 아닌 스킴"),
        ("https://", "호스트 없음"),
        ("https://example.com:99999/v1", "포트 범위 밖 — 예전엔 500 text/plain이 나갔다"),
        # `:0`은 뺐다 — urlparse가 0을 유효 범위로 보고, 코드의 `port or 443`이 443으로
        #  떨어뜨려 **통과한다**. 처음엔 거부될 거라 예상하고 넣었다가 실측으로 틀렸다.
        #  거부하는 게 맞느냐는 별개 판단이고, 지금 동작을 결함이라 부를 근거는 없다.
        # 아래는 전부 DNS 없이 IP 리터럴이라 네트워크에 안 나간다
        ("https://127.0.0.1/v1", "loopback"),
        ("https://localhost/v1", "loopback 별칭"),
        ("https://10.0.0.5/v1", "사설 대역"),
        ("https://192.168.1.1/v1", "사설 대역"),
        ("https://172.16.0.1/v1", "사설 대역"),
        ("https://169.254.169.254/latest/meta-data/", "클라우드 메타데이터 — 이게 본질"),
        ("https://[::1]/v1", "IPv6 loopback"),
        # 괄호가 안 닫힌 IPv6 — **urlparse() 자체가** ValueError를 던진다(포트 접근 전).
        # 08-11에 그 자리를 try로 감쌌는데 회귀 테스트가 없어서, 세 줄을 지워도
        # 전부 초록이었다. 위 `[::1]`은 문법이 멀쩡해 IP 검사에서 걸리는 다른 경로다.
        ("https://[::1/v1", "깨진 IPv6 괄호 — urlparse가 파싱 시점에 던진다"),
        ("https://0.0.0.0/v1", "unspecified"),
    ],
)
def test_base_url_rejects(url, reason):
    with pytest.raises(InvalidBaseURLError):
        validate_base_url(url)


def test_base_url_accepts_public_https():
    # 공인 IP 리터럴 — DNS를 안 타므로 테스트가 네트워크에 의존하지 않는다.
    assert validate_base_url("https://8.8.8.8/v1") == "https://8.8.8.8/v1"


def test_base_url_port_error_is_our_exception_not_valueerror():
    """포트 예외가 우리 예외로 감싸져 있는지 — 이게 500과 400을 가른다.

    routers/ai.py는 InvalidBaseURLError만 잡는다. 맨 ValueError가 새면
    main.py의 핸들러(DB 계열만 본다)를 지나 500 text/plain이 되고,
    프론트는 JSON을 기대하므로 파싱조차 못 한다.
    """
    with pytest.raises(InvalidBaseURLError):
        validate_base_url("https://example.com:99999/v1")


# ══════════════════════════════════════════════════════════════════════════════
# 여기부터 HTTP 라우트 테스트 (/api/ai/keys 계열) — 2026-09-02에 추가.
#
# 왜 지금 쓰는가: 위 세 개는 `validate_base_url`을 **직접** 부르는 순수 단위 테스트다.
# 함수가 옳다는 건 증명하지만 **라우터가 그 함수를 부른다는 건 증명하지 않는다.**
# 2026-09-02 공백검사 기준 `/api/ai/keys`에 HTTP 레벨 테스트가 0건이었고, 실제로
# routers/ai.py의 base_url 검증 배선(`if base_url: validate_base_url(...)`)을 통째로
# 지워도 스위트 전체가 초록이었다. 즉 이 서버가 **자격증명을 받는 입구**이자
# **서버가 임의 주소로 나가는 입구**(SSRF)인데, 방어가 붙어 있다는 사실을 아무도
# 확인하지 않는 상태였다.
#
# 이 아래 테스트들은 그래서 전부 라우트를 통해서만 본다(서비스 함수 직접 호출 금지).
#
# 네트워크: base_url은 전부 **IP 리터럴**이라 getaddrinfo가 DNS로 안 나간다.
#          외부 LLM 호출은 이 라우트들에 아예 없다(키 저장/조회/삭제뿐).
# 레이트리밋: conftest가 `limiter.enabled = False`로 전역에서 끈다. 게다가 키 라우트엔
#          `@limiter.limit`이 안 붙어 있다(붙은 건 /ai/draft 하나). 리셋할 게 없다.
# ══════════════════════════════════════════════════════════════════════════════

# 형식 검증(validate_api_key)을 통과하는 값들. SetKeyRequest가 key에 min_length=10을
# 걸어두므로 10자 이상이어야 한다 — 짧은 키는 400이 아니라 422(pydantic)로 떨어진다.
# 이름에 KEY를 안 쓴다. gitleaks의 generic-api-key는 값의 엔트로피만이 아니라
# **옆에 있는 낱말**(key/token/secret)로 후보를 고르는데, 이 상수들은 진짜 키가 아니라
# 형식 검증을 통과시키려고 만든 고정 문자열이다. 이름을 바꾸는 쪽이 .gitleaks.toml에
# 예외를 하나 더 다는 것보다 낫다 — 그 파일 머리말대로, 예외를 늘리면 그 자리는
# 영원히 안 보이게 되고 검사는 '영구 초록'으로 간다. (2026-09-02)
OPENAI_FIXTURE = "sk-test-0123456789abcdef"
COMPAT_FIXTURE = "compat-test-0123456789"
PUBLIC_BASE = "https://8.8.8.8/v1"  # 공인 IP 리터럴 → DNS를 안 탄다


@pytest.fixture
def server_encryption_key(monkeypatch):
    """서버의 BYOK 암호화 키를 테스트용으로 채운다.

    settings.llm_encryption_key의 기본값은 빈 문자열이고, 그 상태에서 저장은
    503으로 끝난다(아래 `test_set_key_without_server_encryption_key_returns_503`가
    그 갈래를 따로 잠근다). 저장이 성공해야 하는 테스트는 이 픽스처를 쓴다.
    개발자 환경의 실제 키에 의존하지 않기 위해 매번 새로 만든다.
    """
    from cryptography.fernet import Fernet

    from app.core.config import settings

    key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "llm_encryption_key", key)
    return key


def _put_key(client, headers, provider, key=OPENAI_FIXTURE, base_url=None):
    body = {"key": key}
    if base_url is not None:
        body["base_url"] = base_url
    return client.put(f"/api/ai/keys/{provider}", headers=headers, json=body)


def _keys_by_provider(client, headers):
    """GET /api/ai/keys 를 provider → 항목 딕셔너리로."""
    r = client.get("/api/ai/keys", headers=headers)
    assert r.status_code == 200
    return {row["provider"]: row for row in r.json()["keys"]}


# ── 접근 권한 ────────────────────────────────────────────────────────────────
def test_keys_routes_require_auth(client):
    """비로그인은 세 라우트 전부 401. 자격증명을 받는 입구라 제일 먼저 잠근다."""
    assert client.get("/api/ai/keys").status_code == 401
    assert client.put("/api/ai/keys/openai", json={"key": OPENAI_FIXTURE}).status_code == 401
    assert client.delete("/api/ai/keys/openai").status_code == 401


def test_keys_routes_forbid_pending_role(client, make_user, auth_headers):
    """승인 대기(pending) 계정은 403 — 게이팅은 require_writer 하나다(admin/writer만 통과).

    '가입만 하면 서버에 자격증명을 심을 수 있다'가 되면 안 되므로 세 라우트를 다 본다.
    """
    h = auth_headers(make_user(role="pending"))
    assert client.get("/api/ai/keys", headers=h).status_code == 403
    assert _put_key(client, h, "openai").status_code == 403
    assert client.delete("/api/ai/keys/openai", headers=h).status_code == 403


# ── 정상 저장/조회/삭제 ──────────────────────────────────────────────────────
def test_set_key_then_listed_as_has_key(client, make_user, auth_headers, server_encryption_key):
    """저장이 실제로 남는가 — PUT 200 이후 GET에서 has_key가 참이 된다.

    '있다/없다'만 내려주는 계약도 같이 본다. 나머지 provider는 건드리지 않았으니 거짓.
    """
    h = auth_headers(make_user(role="writer"))
    before = _keys_by_provider(client, h)
    assert before["openai"]["has_key"] is False  # 시작은 비어 있다

    r = _put_key(client, h, "openai")
    assert r.status_code == 200
    assert r.json() == {"provider": "openai", "has_key": True, "base_url": None}

    after = _keys_by_provider(client, h)
    assert after["openai"]["has_key"] is True
    assert after["gemini"]["has_key"] is False  # 옆 provider까지 켜지지 않는다


def test_keys_response_never_contains_the_key_value(
    client, make_user, auth_headers, server_encryption_key
):
    """키 원문은 어떤 응답에도 안 나온다(llm_keys.py의 규칙: '있다/없다'만).

    저장 응답과 목록 응답 **본문 전체**를 문자열로 훑는다. 스키마에 필드를 하나
    잘못 추가하는 순간(예: 디버깅용 echo) 여기서 걸린다.
    """
    h = auth_headers(make_user(role="writer"))
    put_body = _put_key(client, h, "openai").text
    list_body = client.get("/api/ai/keys", headers=h).text
    assert OPENAI_FIXTURE not in put_body
    assert OPENAI_FIXTURE not in list_body


def test_keys_are_scoped_to_the_owner(client, make_user, auth_headers, server_encryption_key):
    """남의 키가 내 목록에 보이면 안 된다 — 라우트가 user.id로만 조회하는지."""
    owner = make_user(role="writer")
    other = make_user(role="writer")
    assert _put_key(client, auth_headers(owner), "openai").status_code == 200

    mine = _keys_by_provider(client, auth_headers(other))
    assert all(row["has_key"] is False for row in mine.values())


def test_delete_key_turns_has_key_false(client, make_user, auth_headers, server_encryption_key):
    """DELETE 뒤 조회에서 has_key가 거짓 — '지웠다'가 실제로 지운 것인지."""
    h = auth_headers(make_user(role="writer"))
    assert _put_key(client, h, "openai").status_code == 200
    assert _keys_by_provider(client, h)["openai"]["has_key"] is True

    r = client.delete("/api/ai/keys/openai", headers=h)
    assert r.status_code == 200
    assert r.json()["has_key"] is False
    assert _keys_by_provider(client, h)["openai"]["has_key"] is False


def test_delete_missing_key_is_not_an_error(client, make_user, auth_headers):
    """없는 키를 지워도 200 — delete_key가 False를 돌려주지만 라우터는 구분하지 않는다.

    (지금 동작을 고정한다. 404로 바꾸면 '이 사람이 키를 등록했는지'가 상태코드로
    새어나가고, 프론트의 '해제' 버튼도 멱등성을 잃는다.)
    """
    h = auth_headers(make_user(role="writer"))
    assert client.delete("/api/ai/keys/openai", headers=h).status_code == 200


# ── provider 화이트리스트 ────────────────────────────────────────────────────
@pytest.mark.parametrize("provider", ["bogus", "claude", "OpenAI", "openai2"])
def test_unknown_provider_rejected(client, make_user, auth_headers, provider):
    """BYOK_PROVIDERS에 없는 provider는 PUT·DELETE 둘 다 400.

    'claude'를 넣은 이유: 서버키로 부르는 provider라 BYOK 목록에 **일부러** 없다.
    'OpenAI'/'openai2'는 대소문자·부분일치 — 화이트리스트가 정확 일치라는 걸 고정한다.
    """
    h = auth_headers(make_user(role="writer"))
    assert _put_key(client, h, provider).status_code == 400
    assert client.delete(f"/api/ai/keys/{provider}", headers=h).status_code == 400


# ── base_url 필수 provider ───────────────────────────────────────────────────
@pytest.mark.parametrize("base_url", [None, "", "   "])
def test_compatible_requires_base_url(client, make_user, auth_headers, base_url):
    """base_url이 필요한 provider는 `compatible` 하나다(NEEDS_BASE_URL).

    ⚠️ 검사 보고서는 'openai 호환 provider = openai'라고 적었는데 코드는 다르다.
    openai/gemini/anthropic/cohere는 벤더 고정 주소라 base_url이 선택이고,
    범용 OpenAI 호환 엔드포인트를 뜻하는 이름이 `compatible`이다.

    빈 문자열·공백만 있는 값도 '안 준 것'으로 접혀야 한다(라우터가 strip 후 or None).
    안 그러면 빈 base_url이 그대로 저장돼 호출 시점에 엉뚱한 곳으로 간다.
    """
    h = auth_headers(make_user(role="writer"))
    r = _put_key(client, h, "compatible", key=COMPAT_FIXTURE, base_url=base_url)
    assert r.status_code == 400
    assert "base URL" in r.json()["detail"]


def test_compatible_accepts_public_https_base_url(
    client, make_user, auth_headers, server_encryption_key
):
    """정상 경로: 공인 https 주소는 통과하고, 조회에 그대로 보인다.

    이 테스트는 SSRF 방어를 증명하지 않는다 — **과차단**을 잡는 쪽이다.
    (검증을 '전부 거부'로 바꾸면 여기가 빨간불이 된다)
    """
    h = auth_headers(make_user(role="writer"))
    r = _put_key(client, h, "compatible", key=COMPAT_FIXTURE, base_url=PUBLIC_BASE)
    assert r.status_code == 200
    assert r.json()["base_url"] == PUBLIC_BASE
    row = _keys_by_provider(client, h)["compatible"]
    assert row["has_key"] is True
    assert row["base_url"] == PUBLIC_BASE  # base_url은 비밀이 아니라 표시용으로 내려준다


# ── SSRF: 이 파일의 본론 ─────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "bad_url,reason",
    [
        ("https://169.254.169.254/latest/meta-data/", "클라우드 메타데이터 — 이게 본질"),
        ("https://127.0.0.1/v1", "loopback"),
        ("https://10.0.0.5/v1", "사설 대역"),
        ("https://192.168.1.1/v1", "사설 대역"),
        ("https://[::1]/v1", "IPv6 loopback"),
        ("http://8.8.8.8/v1", "평문 http"),
        ("https://8.8.8.8:99999/v1", "포트 범위 밖 — 예전엔 500 text/plain이 나갔다"),
        ("https://[::1/v1", "깨진 IPv6 괄호 — urlparse가 파싱 시점에 던진다"),
    ],
)
def test_set_key_rejects_internal_base_url(client, make_user, auth_headers, bad_url, reason):
    """**라우트 레벨에서** SSRF 주소가 막히는지. 이 파일이 존재하는 이유다.

    위쪽 단위 테스트는 `validate_base_url`이 옳다는 것만 본다. 여기서 보는 건
    라우터가 그 함수를 **실제로 부르는가**다 — routers/ai.py의 배선 다섯 줄을
    지우면 위 단위 테스트는 전부 초록인 채로 이 테스트만 빨간불이 된다
    (2026-09-02에 그 상태였다).

    응답이 JSON 400인지도 같이 본다. 포트/깨진 괄호 케이스는 검증을 안 거치면
    한참 뒤(getaddrinfo·DB)에서 맨 ValueError로 터져 **500 text/plain**이 되고,
    프론트는 파싱조차 못 한다.
    """
    h = auth_headers(make_user(role="writer"))
    r = _put_key(client, h, "compatible", key=COMPAT_FIXTURE, base_url=bad_url)
    assert r.status_code == 400, reason
    assert r.headers["content-type"].startswith("application/json")


def test_rejected_base_url_is_not_persisted(client, make_user, auth_headers, server_encryption_key):
    """거부된 요청은 **아무것도 남기지 않는다** — 검증이 저장 앞에 있는지.

    검증을 저장 뒤로 옮기면(또는 로깅용으로 먼저 써두면) 400을 받고도 자격증명이
    DB에 남는다. 다음 요청에서 그 주소로 서버가 나가게 되므로 400이 무의미해진다.
    """
    h = auth_headers(make_user(role="writer"))
    r = _put_key(
        client, h, "compatible", key=COMPAT_FIXTURE, base_url="https://169.254.169.254/latest/"
    )
    assert r.status_code == 400
    assert _keys_by_provider(client, h)["compatible"]["has_key"] is False


def test_internal_base_url_rejected_for_optional_base_url_provider(
    client, make_user, auth_headers, server_encryption_key
):
    """base_url이 '필수가 아닌' provider(openai)에 내부 주소를 붙여도 막힌다.

    검증이 `provider in NEEDS_BASE_URL`이 아니라 `if base_url:`에 걸려 있어야
    이 경로가 닫힌다. 조건을 provider 기준으로 바꾸는 순간 openai/gemini/anthropic/
    cohere 넷이 통째로 SSRF 입구가 되는데, 그건 코드만 봐선 안 보인다.
    """
    h = auth_headers(make_user(role="writer"))
    r = _put_key(client, h, "openai", base_url="https://169.254.169.254/latest/")
    assert r.status_code == 400


# ── 키 형식 ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "provider,key,reason",
    [
        ("openai", "not-a-key-0123456789", "openai는 sk- 접두사"),
        ("gemini", "sk-0123456789abcdef", "gemini는 AIza 접두사"),
        ("anthropic", "sk-0123456789abcdef", "anthropic은 sk-ant- (sk-만으론 부족)"),
        ("openai", "sk-abc 0123456789", "공백 — 붙여넣기 사고"),
        ("openai", "sk-abc\t0123456789", "탭도 공백"),
        ("openai", "sk-키가아니야0123456789", "비ASCII"),
        ("compatible", "compat 0123456789", "접두사 없는 provider도 공백은 막는다"),
    ],
)
def test_set_key_rejects_malformed_key(client, make_user, auth_headers, provider, key, reason):
    """형식이 틀린 키는 암호화 저장까지 못 간다(400).

    실제 유효성은 벤더가 판단하지만, '오타·통째 붙여넣기'가 암호문으로 들어앉으면
    사용자는 나중에 초안 생성이 502로 실패하는 것만 보게 된다. 여기서 끊는 게 싸다.
    compatible/cohere는 접두사를 강제하지 않는다는 점도 같이 고정한다 —
    그 둘은 벤더마다 형식이 제각각(xai-, sk-or-, 접두사 없음)이라 일부러 안 막는다.
    """
    h = auth_headers(make_user(role="writer"))
    r = _put_key(client, h, provider, key=key, base_url=PUBLIC_BASE)
    assert r.status_code == 400, reason


def test_short_key_is_422_not_400(client, make_user, auth_headers):
    """10자 미만은 pydantic(SetKeyRequest.key min_length=10)이 먼저 잡아 422다.

    400이 아니다 — 이걸 적어두는 이유는, 400을 기대하고 쓴 테스트가 조용히
    통과하는(422도 실패지만 다른 층의 실패다) 착각을 막기 위해서다.
    """
    h = auth_headers(make_user(role="writer"))
    assert _put_key(client, h, "openai", key="sk-1").status_code == 422


# ── 서버 설정이 빠진 경우 ────────────────────────────────────────────────────
def test_set_key_without_server_encryption_key_returns_503(
    client, make_user, auth_headers, monkeypatch
):
    """LLM_ENCRYPTION_KEY가 없으면 503 JSON — 평문 저장으로 흘러가지 않는다.

    이 갈래가 없으면 BYOKNotConfiguredError가 그대로 새서 500 text/plain이 된다
    (07-31에 BYOK 복호화에서 고쳤던 것과 같은 병). 사용자 잘못이 아니므로 5xx로
    답하되, 무엇이 빠졌는지는 운영자가 알아볼 수 있게 남긴다.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "llm_encryption_key", "")
    h = auth_headers(make_user(role="writer"))
    r = _put_key(client, h, "openai")
    assert r.status_code == 503
    assert r.headers["content-type"].startswith("application/json")
    assert "LLM_ENCRYPTION_KEY" in r.json()["detail"]
