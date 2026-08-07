#!/usr/bin/env python
"""VAPID 키쌍을 만들어 .env에 넣을 형태로 출력한다.

Web Push는 "이 알림을 보낸 게 정말 그 서버냐"를 VAPID(RFC 8292)로 증명한다.
서버가 개인키로 JWT를 서명하고, 브라우저는 구독할 때 받아둔 공개키로 검증한다.

  scripts/gen_vapid_keys.py          # 새 키쌍 출력
  scripts/gen_vapid_keys.py --check  # .env에 있는 키가 실제로 짝이 맞는지 확인

**한 번 만들면 바꾸지 않는다.** 공개키는 브라우저의 구독 정보에 박혀 있어서,
키를 갈면 기존 구독이 전부 무효가 된다(발송이 조용히 실패한다). 갈아야 한다면
구독 테이블을 비우고 사용자에게 다시 켜달라고 해야 한다.

공개키는 비밀이 아니다 — 프론트가 그 값으로 구독하므로 어차피 공개된다.
개인키만 .env에 두고, 다른 시크릿과 같은 취급을 한다(이미지에 굽지 않는다).
"""
import argparse
import base64
import os
import sys

# 스크립트로 직접 실행하면 sys.path에 잡히는 건 scripts/라 app 패키지가 안 보인다.
# 저장소의 다른 스크립트(create_user.py)와 같은 방식으로 backend/를 얹는다.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402


def _b64(raw: bytes) -> str:
    """base64url, 패딩 없이 — Web Push의 모든 키 인코딩이 이 형식이다."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _public_bytes(private_key: ec.EllipticCurvePrivateKey) -> bytes:
    """비압축 좌표(0x04 + X + Y, 65바이트). 브라우저의 applicationServerKey 형식."""
    from cryptography.hazmat.primitives import serialization

    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )


def generate() -> tuple[str, str]:
    key = ec.generate_private_key(ec.SECP256R1())
    # 개인키는 32바이트 스칼라를 base64url로. py_vapid.Vapid01.from_string이 이 형식을 읽는다.
    private_raw = key.private_numbers().private_value.to_bytes(32, "big")
    return _b64(private_raw), _b64(_public_bytes(key))


def check() -> int:
    """.env에 들어 있는 두 값이 실제로 같은 키쌍인지 본다.

    왜 필요한가 — 공개키와 개인키를 따로 붙여넣다가 어긋나면, 구독은 멀쩡히
    되는데 **발송만 조용히 실패한다**(브라우저가 서명 검증에 실패해 무시).
    증상이 '알림이 안 온다'뿐이라 원인을 찾기가 어렵다. 그래서 재보는 수단을 둔다.
    """
    from py_vapid import Vapid01

    from app.core.config import settings

    if not settings.push_enabled:
        print("VAPID 키가 설정돼 있지 않습니다 (푸시 기능 꺼짐).")
        return 1
    vapid = Vapid01.from_string(private_key=settings.vapid_private_key)
    derived = _b64(_public_bytes(vapid.private_key))
    if derived == settings.vapid_public_key:
        print(f"✅ 키쌍 일치 (공개키 {derived[:16]}…)")
        return 0
    print("❌ 짝이 맞지 않습니다 — 개인키에서 나온 공개키가 설정값과 다릅니다.")
    print(f"   .env의 VAPID_PUBLIC_KEY : {settings.vapid_public_key[:24]}…")
    print(f"   개인키에서 유도한 값     : {derived[:24]}…")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help=".env의 키쌍이 맞는지 확인")
    args = ap.parse_args()

    if args.check:
        return check()

    private, public = generate()
    print("# .env 에 아래 두 줄을 넣으세요 (공개키는 비밀이 아닙니다)")
    print(f"VAPID_PUBLIC_KEY={public}")
    print(f"VAPID_PRIVATE_KEY={private}")
    print()
    print("# 푸시 서비스가 문제 시 연락할 곳 — mailto: 또는 https: 여야 합니다")
    print("VAPID_SUBJECT=mailto:your-address@example.com")
    print()
    print("⚠️  한 번 정하면 바꾸지 마세요. 키를 갈면 기존 구독이 전부 무효가 됩니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
