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
