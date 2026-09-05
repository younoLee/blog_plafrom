"""레이트리밋 **키**를 정하는 client_ip() 회귀 테스트 (2026-09-04 검사 BQ-2 신설).

이 한 함수가 IP 기반 제한 전부의 기준이다 — 로그인 10/분 · 가입 5/시간 · 댓글 20/시간 ·
AI 초안 10/시간이 여기서 나온 값을 키로 센다. 그런데 09-04 검사 시점의 coverage 에서
`if xff:` 안쪽(파싱 · 홉 계산 · `parts[-idx]`)이 **한 번도 실행된 적이 없었다.**

왜 위험한가: `parts[-idx]` 를 `parts[idx - 1]` 로 바꾸는 한 글자 회귀는 **클라이언트가
위조해 넣은 맨 앞 값**을 키로 쓰게 만든다. 그러면 요청마다 다른 IP 인 척할 수 있어
모든 IP 제한이 무력화되는데, CI 는 초록이고 밖에서도 아무 신호가 없다 —
막던 것이 사라진 것은 조용하다. 함수 주석이 그 위험을 적어두고도 시험은 0건이었다.

DB 도 앱도 필요 없다. Request 는 헤더와 client 만 있으면 되므로 scope 로 직접 만든다.
"""

import pytest
from starlette.requests import Request

from app.core import ratelimit
from app.core.ratelimit import client_ip

VIEWER = "203.0.113.7"  # RFC 5737 문서용 대역 — 실제 값은 저장소에 안 쓴다
EDGE = "203.0.113.20"
LB = "203.0.113.30"


def make_request(xff: str | None = None, peer: str = "198.51.100.9") -> Request:
    headers = [(b"x-forwarded-for", xff.encode())] if xff is not None else []
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/posts",
            "headers": headers,
            "client": (peer, 12345),
        }
    )


@pytest.fixture
def hops(monkeypatch):
    """settings.trusted_proxy_hops 를 시험마다 바꾼다. 이 값이 인프라 모양(1홉=현행
    CloudFront→EC2, 2홉=ECS CloudFront→ALB→task)을 따라가므로 둘 다 재현한다."""

    def set_hops(n: int) -> None:
        monkeypatch.setattr(ratelimit.settings, "trusted_proxy_hops", n)

    return set_hops


def test_1홉이면_맨_뒤를_쓴다(hops):
    """현행 배치. 맨 뒤 = 가장 바깥 신뢰 프록시(CloudFront)가 관측한 진짜 방문자다."""
    hops(1)
    assert client_ip(make_request(f"{VIEWER}, {EDGE}")) == EDGE


def test_2홉이면_뒤에서_두_번째를_쓴다(hops):
    """ECS 배치. 맨 뒤는 ALB 가 본 CloudFront 엣지 IP 라, 그걸 키로 쓰면 모든 방문자가
    한 키로 묶여 제한이 통째로 무력해진다."""
    hops(2)
    assert client_ip(make_request(f"{VIEWER}, {EDGE}, {LB}")) == EDGE


def test_맨_앞_값은_절대_키가_되지_않는다(hops):
    """**이 파일이 존재하는 이유.** 맨 앞은 클라이언트가 위조해 넣을 수 있다 —
    거기서 키를 뽑으면 요청마다 다른 IP 인 척해서 제한을 우회한다."""
    hops(1)
    forged = "1.1.1.1"
    assert client_ip(make_request(f"{forged}, {VIEWER}, {EDGE}")) == EDGE


def test_항목이_홉_수보다_적으면_맨_앞을_쓴다(hops):
    """신뢰 프록시를 덜 거친 비정상 경로. idx=len 이라 parts[0] 이 되는데, 이 경로 자체가
    오리진 SG 로 막혀 있다는 게 함수 주석의 전제다 — 동작을 못박아 둔다."""
    hops(2)
    assert client_ip(make_request(VIEWER)) == VIEWER


def test_공백과_빈_항목이_섞여도_실제_값을_고른다(hops):
    hops(1)
    assert client_ip(make_request(f"  {VIEWER} , , {EDGE}  ")) == EDGE


def test_헤더가_없으면_소켓_상대를_쓴다(hops):
    """로컬·직접 접속. 폴백이 죽으면 키가 전부 같아져 한 사람이 전체를 잠글 수 있다."""
    hops(1)
    assert client_ip(make_request(None, peer="198.51.100.9")) == "198.51.100.9"


def test_헤더가_비어_있으면_소켓_상대를_쓴다(hops):
    """빈 문자열·쉼표만 있는 값도 '값이 없다'로 접힌다(parts 가 빈 리스트)."""
    hops(1)
    assert client_ip(make_request(" , ", peer="198.51.100.9")) == "198.51.100.9"
