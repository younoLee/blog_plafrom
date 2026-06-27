from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def client_ip(request: Request) -> str:
    """진짜 클라이언트 IP (레이트리밋 키).

    CloudFront 같은 신뢰 프록시는 진짜 클라 IP를 X-Forwarded-For의 '맨 뒤'에 덧붙인다.
    '맨 앞'은 클라이언트가 마음대로 넣을 수 있어(위조) → 그걸 키로 쓰면 요청마다 다른
    IP인 척 레이트리밋을 통째로 우회당한다. 그래서 맨 뒤(프록시가 실제 관측한 IP)를 쓴다.
    주의: 백엔드를 CloudFront 거치지 않고 직접(:8000) 칠 수 있으면 이 헤더째 위조되니,
    EC2 보안그룹에서 8000을 CloudFront에만 열어야 완전해진다(인프라 측 조치)."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[-1].strip()
    return get_remote_address(request)


# 앱 전역에서 공유하는 리미터 (메모리 저장 — 단일 인스턴스라 충분)
limiter = Limiter(key_func=client_ip)
