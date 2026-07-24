from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings


def client_ip(request: Request) -> str:
    """진짜 클라이언트 IP (레이트리밋 키).

    신뢰 프록시(CloudFront·ALB)는 각자 관측한 IP를 X-Forwarded-For '맨 뒤'에 하나씩 덧붙인다.
    '맨 앞'은 클라이언트가 위조해 넣을 수 있어(그걸 키로 쓰면 요청마다 다른 IP인 척 우회당함),
    뒤에서 hops번째 = 가장 바깥 신뢰 프록시가 실제 관측한 IP를 쓴다.
    - 현행 CloudFront→EC2 = 1홉 → 맨 뒤(=viewer).
    - ECS CloudFront→ALB→task = 2홉 → 뒤에서 2번째(=viewer). 맨 뒤는 ALB가 본 CloudFront 엣지 IP다.
      홉 수가 틀리면 모든 IP 제한이 엣지 IP를 키로 잡아 무력화된다 → settings.trusted_proxy_hops로 맞춘다.
    주의: CloudFront를 우회해 오리진을 직접 치면 헤더째 위조되니, 오리진 SG를 CloudFront에만
    여는 인프라 측 조치가 함께 있어야 완전하다."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            # XFF가 홉 수보다 짧으면(직접 접근 등) 가장 앞(가장 바깥에서 관측된 값)으로 폴백.
            idx = min(settings.trusted_proxy_hops, len(parts))
            return parts[-idx]
    return get_remote_address(request)


# 앱 전역에서 공유하는 리미터 (메모리 저장 — 단일 인스턴스라 충분)
limiter = Limiter(key_func=client_ip)
