#!/usr/bin/env python3
"""훈련 스택에 푸시 구독을 D개 심는다. **컨테이너 안에서** 돈다.

  docker compose ... exec -T backend python /chaos/seed_push.py <작성자이메일> <D>

왜 필요한가 (2026-08-27) —
  08-26 회차는 푸시 hang 을 **D=3 으로만** 쟀고 D=20·D=100 은 산술 추정이었다.
  추정으로 남은 이유가 "구독을 20개 만들 방법이 없어서"다. 브라우저로 만들면 기기가
  20대 필요하고, 손으로 SQL 을 치면 p256dh 가 실제 공개키가 아니라 암호화 단계에서
  터진다 — 그러면 재는 것이 '푸시 발송'이 아니라 '키 파싱 실패'가 된다.

  **커넥션 풀 고갈 지점(동시 20건)도 추정선까지만 확인됐다.** 그 선을 실제로 밟으려면
  기기 수를 마음대로 정할 수 있어야 한다. 그게 이 스크립트의 존재 이유다.

무엇이 진짜여야 하는가 —
  · endpoint : `is_allowed_endpoint` 를 통과해야 한다(push.py:88-97). 그래서 fcm 을 쓴다.
               DNS 는 blackhole 로 가로채져 있으므로 바깥으로 나가지 않는다.
  · p256dh   : **진짜 P-256 공개키여야 한다.** http_ece 가 이걸로 ECDH 를 하므로
               아무 문자열이나 넣으면 HTTP 호출 **전에** 예외가 나고, 주입은 한 번도
               안 밟힌다. 훈련이 "푸시가 죽었다"고 적는데 원인이 우리 시드인 상황.
  · auth     : 16바이트. 표준값이라 길이가 틀리면 같은 자리에서 터진다.

만든 것은 전부 `chaos-push-*@example.com` 이라 down.sh 의 볼륨 삭제와 함께 사라진다.
"""
from __future__ import annotations

import base64
import os
import secrets
import sys

sys.path.insert(0, "/app")

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from sqlalchemy import delete, func, select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models.author_subscription import AuthorSubscription  # noqa: E402
from app.models.push_subscription import PushSubscription  # noqa: E402
from app.models.user import User  # noqa: E402

PREFIX = "chaos-push-"


def b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def keypair() -> tuple[str, str]:
    """구독자 쪽 키. 브라우저가 `pushManager.subscribe()` 로 돌려주는 것과 같은 모양."""
    k = ec.generate_private_key(ec.SECP256R1())
    pub = k.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return b64(pub), b64(secrets.token_bytes(16))


def main() -> int:
    if len(sys.argv) < 3:
        print("사용: seed_push.py <작성자이메일> <기기수>", file=sys.stderr)
        return 2
    author_email, count = sys.argv[1], int(sys.argv[2])

    db = SessionLocal()
    try:
        author = db.scalar(
            select(User).where(func.lower(User.email) == author_email.lower())
        )
        if author is None:
            print(f"! 작성자를 못 찾았다: {author_email}", file=sys.stderr)
            return 1

        # 매번 같은 출발점에서 시작한다. 지난 주입의 구독이 남아 있으면 D 가 누적돼
        # "D=20 을 쟀다"가 실제로는 D=23 이 된다 — 그 3 이 어디서 왔는지 나중에 모른다.
        old = db.scalars(
            select(User.id).where(User.email.like(f"{PREFIX}%"))
        ).all()
        if old:
            db.execute(delete(PushSubscription).where(PushSubscription.user_id.in_(old)))
            db.execute(delete(AuthorSubscription).where(AuthorSubscription.subscriber_id.in_(old)))
            db.execute(delete(User).where(User.id.in_(old)))
            db.commit()

        pw = hash_password(secrets.token_urlsafe(12))
        for i in range(count):
            u = User(
                email=f"{PREFIX}{i}@example.com",
                hashed_password=pw,
                role="pending",
                email_verified=True,
                display_name=f"chaos-push-{i}",
            )
            db.add(u)
            db.flush()
            # approved·notify 가 둘 다 True 여야 대상에 들어온다(push.py 의 조회 조건).
            # 하나라도 빠뜨리면 D 를 아무리 올려도 발송 대상이 0이고, 그걸
            # "푸시가 빨랐다"로 읽게 된다.
            db.add(
                AuthorSubscription(
                    subscriber_id=u.id, author_id=author.id, approved=True, notify=True
                )
            )
            p256dh, auth = keypair()
            db.add(
                PushSubscription(
                    user_id=u.id,
                    endpoint=f"https://fcm.googleapis.com/fcm/send/chaos-{i}-{secrets.token_hex(6)}",
                    p256dh=p256dh,
                    auth=auth,
                )
            )
        db.commit()

        # **심은 것이 실제로 대상에 잡히는지 같은 조건으로 되센다.** 심었다는 것과
        # 발송 대상이 된다는 것은 다른 명제다(원칙 4: "설정했다"와 "동작한다"는 다르다).
        n = db.scalar(
            select(func.count())
            .select_from(PushSubscription)
            .join(
                AuthorSubscription,
                AuthorSubscription.subscriber_id == PushSubscription.user_id,
            )
            .join(User, User.id == PushSubscription.user_id)
            .where(
                AuthorSubscription.author_id == author.id,
                AuthorSubscription.approved.is_(True),
                AuthorSubscription.notify.is_(True),
                User.role != "banned",
            )
        )
        print(f"심은 기기 {count}대 / 발송 대상으로 잡히는 기기 {n}대 (작성자 {author_email})")
        return 0 if n == count else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
