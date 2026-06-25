from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def client_ip(request: Request) -> str:
    """진짜 클라이언트 IP. CloudFront/프록시 뒤에서는 직접 연결 IP가 엣지 IP라
    X-Forwarded-For의 맨 앞(최초 요청자)을 우선 사용한다."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return get_remote_address(request)


# 앱 전역에서 공유하는 리미터 (메모리 저장 — 단일 인스턴스라 충분)
limiter = Limiter(key_func=client_ip)
