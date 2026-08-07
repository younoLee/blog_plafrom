"""Web Push 발송 — VAPID(RFC 8292) 서명 + aes128gcm(RFC 8188) 암호화.

**왜 pywebpush를 안 쓰나** — pywebpush는 이 파일이 쓰는 바로 그 두 라이브러리
(py_vapid, http_ece)를 감싼 것이다. 즉 '틀리면 조용히 깨지는' 부분(서명·암호화)은
어느 쪽이든 같은 코드가 처리하고, 감싸개가 더 해주는 건 헤더 조립과 POST뿐이다.
그 대가가 aiohttp 생태계 11개 패키지라 직접 조립하기로 했다. 여기서 우리가 쓴
코드는 전부 검토 가능한 것들이고, 암호화가 맞게 배선됐는지는 테스트에서
'암호화 → 복호화' 왕복으로 실제로 재본다(tests/test_push.py).

**Vapid01이 아니라 Vapid02를 쓴다.** 01은 draft 시절 형식(`Authorization: WebPush …`)
이고 02가 RFC 8292(`Authorization: vapid t=…,k=…`)다. Apple의 Web Push가 후자를
요구하므로, iOS를 포기하지 않으려면 02여야 한다.
"""
import base64
import json
import logging
import os
import time
from urllib.parse import urlparse

import http_ece
import httpx
from cryptography.hazmat.primitives.asymmetric import ec
from py_vapid import Vapid02

from app.core.config import settings

logger = logging.getLogger(__name__)

# 푸시 서비스가 수신자를 못 만났을 때 메시지를 얼마나 붙들고 있을지(초).
# 새 글 알림은 하루가 지나면 알림으로서 의미가 옅어지므로 24시간.
TTL_SECONDS = 24 * 60 * 60

# VAPID JWT 유효기간. 표준 상한은 24시간이고, 짧을수록 유출 시 노출이 줄지만
# 발송 때마다 새로 서명하므로 길 이유가 없다.
_JWT_TTL_SECONDS = 12 * 60 * 60


class PushGone(Exception):
    """구독이 영구히 무효(404/410) — 지워야 한다는 신호.

    일시적 실패(5xx·타임아웃)와 반드시 구분한다. 섞으면 푸시 서비스가 잠깐
    흔들릴 때 멀쩡한 구독을 전부 지워버린다."""


def _b64url_decode(value: str) -> bytes:
    """브라우저가 주는 키는 패딩 없는 base64url이다 — 붙여서 디코드한다."""
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _encrypt(payload: bytes, p256dh: str, auth: str) -> bytes:
    """구독자 공개키로 페이로드를 봉인한다(aes128gcm).

    발송할 때마다 **일회용 키쌍(ephemeral)을 새로 만든다.** 재사용하면 같은 키로
    암호화된 메시지가 쌓여 분석 대상이 되고, 무엇보다 aes128gcm은 (키, salt) 조합이
    겹치면 안 된다. salt는 http_ece가 알아서 만들고 암호문 머리에 넣어준다."""
    return http_ece.encrypt(
        payload,
        private_key=ec.generate_private_key(ec.SECP256R1()),
        dh=_b64url_decode(p256dh),
        auth_secret=_b64url_decode(auth),
        version="aes128gcm",
    )


def _vapid_headers(endpoint: str) -> dict[str, str]:
    """이 endpoint의 푸시 서비스를 수신자로 지정한 서명 헤더.

    `aud`는 **엔드포인트 전체가 아니라 오리진**이어야 한다(RFC 8292). 경로까지 넣으면
    푸시 서비스가 401로 거절한다 — 눈으로는 잘 안 보이는 실수라 여기서 잘라둔다."""
    parts = urlparse(endpoint)
    vapid = Vapid02.from_string(private_key=settings.vapid_private_key)
    return vapid.sign(
        {
            "aud": f"{parts.scheme}://{parts.netloc}",
            "sub": settings.vapid_subject,
            "exp": int(time.time()) + _JWT_TTL_SECONDS,
        }
    )


def send_push(endpoint: str, p256dh: str, auth: str, data: dict) -> None:
    """구독 하나에 알림을 보낸다.

    실패는 두 갈래다:
      - 404/410 → 구독이 영구 무효 → `PushGone` (호출부가 지운다)
      - 그 외    → 일시적일 수 있으므로 로그만 남기고 삼킨다. 알림 하나 때문에
                   글 발행 요청이 실패하면 안 된다.
    """
    body = _encrypt(json.dumps(data, ensure_ascii=False).encode(), p256dh, auth)
    headers = {
        **_vapid_headers(endpoint),
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
        "TTL": str(TTL_SECONDS),
        # 새 글 알림은 즉시성이 필요 없다. normal이면 절전 중인 기기를 깨우지 않고
        # 다음에 깰 때 전달돼 배터리를 덜 쓴다(high는 잠금화면을 즉시 깨운다).
        "Urgency": "normal",
    }
    with httpx.Client(timeout=10.0) as client:
        res = client.post(endpoint, content=body, headers=headers)
    if res.status_code in (404, 410):
        raise PushGone(f"구독 만료 ({res.status_code})")
    if res.status_code >= 400:
        # 본문에 원인이 담겨 오는 경우가 많다(잘못된 서명·payload 초과 등).
        # 엔드포인트는 그 자체가 기기 식별자라 통째로 찍지 않고 오리진만 남긴다.
        origin = urlparse(endpoint).netloc
        logger.warning(
            "푸시 발송 실패 %s: %s %s", origin, res.status_code, res.text[:200]
        )


def notify_new_post_push(post_id: int, post_title: str, author_id: int) -> None:
    """새 글 알림을 '구독 + 알림 켠' 사람들의 모든 기기로 보낸다.

    이메일 알림(services/email.py의 notify_new_post)과 대상 조건이 완전히 같다 —
    같은 의사표시(author_subscriptions.notify)를 읽고 채널만 다르다. 이메일은
    발신 도메인이 없어 스팸함에 꽂히므로, 실제로 닿는 건 이쪽이다.

    푸시 키가 설정 안 됐으면 조용히 아무것도 안 한다(기능 꺼짐)."""
    if not settings.push_enabled:
        return

    # 백그라운드라 요청 세션과 별개로 자체 세션을 연다(email.py와 같은 이유).
    from sqlalchemy import delete, select

    from app.core.database import SessionLocal
    from app.models.author_subscription import AuthorSubscription
    from app.models.push_subscription import PushSubscription

    db = SessionLocal()
    try:
        subs = db.execute(
            select(
                PushSubscription.id,
                PushSubscription.endpoint,
                PushSubscription.p256dh,
                PushSubscription.auth,
            )
            .join(
                AuthorSubscription,
                AuthorSubscription.subscriber_id == PushSubscription.user_id,
            )
            .where(
                AuthorSubscription.author_id == author_id,
                AuthorSubscription.approved.is_(True),
                AuthorSubscription.notify.is_(True),
            )
        ).all()

        payload = {
            "title": "새 글이 올라왔어",
            "body": post_title,
            # 서비스워커가 알림 클릭 시 열 주소. 절대 경로 대신 앱 라우트를 준다.
            "url": f"/blog/posts/{post_id}",
        }
        dead: list[int] = []
        for sub_id, endpoint, p256dh, auth in subs:
            try:
                send_push(endpoint, p256dh, auth, payload)
            except PushGone:
                dead.append(sub_id)
            except Exception:
                # 한 기기 실패가 나머지 발송을 막지 않게(email.py와 같은 방침)
                logger.exception("푸시 발송 중 예외")

        # 죽은 구독은 그 자리에서 지운다. 안 지우면 매 발행마다 같은 곳에 던지고
        # 실패하며, 사용자 목록의 '기기 수'도 영원히 틀린 값을 보여준다.
        if dead:
            db.execute(delete(PushSubscription).where(PushSubscription.id.in_(dead)))
            db.commit()
            logger.info("만료된 푸시 구독 %d건 정리", len(dead))
    finally:
        db.close()


def _selftest_roundtrip() -> bool:
    """암호화 배선이 맞는지 자체 확인 — 가짜 구독자로 봉인했다가 열어본다.

    브라우저 없이 검증할 수 있는 유일한 지점이라 테스트에서 이걸 쓴다.
    (실제 '알림이 화면에 뜨는가'는 사람이 봐야 한다.)"""
    from cryptography.hazmat.primitives import serialization

    sub_key = ec.generate_private_key(ec.SECP256R1())
    p256dh = base64.urlsafe_b64encode(
        sub_key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
    ).rstrip(b"=").decode()
    auth_secret = os.urandom(16)
    auth = base64.urlsafe_b64encode(auth_secret).rstrip(b"=").decode()

    original = {"title": "새 글이 올라왔어", "body": "한글 제목 확인"}
    sealed = _encrypt(json.dumps(original, ensure_ascii=False).encode(), p256dh, auth)
    opened = http_ece.decrypt(
        sealed, private_key=sub_key, auth_secret=auth_secret, version="aes128gcm"
    )
    return json.loads(opened) == original
