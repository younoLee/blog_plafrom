#!/usr/bin/env python3
"""훈련용 키 생성기. up.sh 가 부른다.

셸 heredoc 안에 파이썬을 중첩해 두면 따옴표가 서로를 먹는다(2026-08-27에 한 번 겪었다).
스크립트로 빼면 그 결합이 사라지고, 무엇보다 **손으로 따로 돌려볼 수 있다.**

여기서 만드는 키는 전부 훈련 스택 전용이다. 운영 키를 쓰지 않는다 —
훈련 스택이 실제 기기로 푸시를 보낼 이유가 없다.
"""
import base64
import sys


def vapid() -> str:
    """Web Push VAPID 키쌍(P-256). 'public private' 한 줄로 낸다."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    def b64(b: bytes) -> str:
        return base64.urlsafe_b64encode(b).decode().rstrip("=")

    k = ec.generate_private_key(ec.SECP256R1())
    pub = k.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    priv = k.private_numbers().private_value.to_bytes(32, "big")
    return f"{b64(pub)} {b64(priv)}"


def fernet() -> str:
    """BYOK 암호화 키. 형식이 안 맞으면 BYOK 경로가 주입이 아니라 설정 오류로 죽는다."""
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode()


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else ""
    if what == "vapid":
        print(vapid())
    elif what == "fernet":
        print(fernet())
    else:
        print("사용: genkeys.py <vapid|fernet>", file=sys.stderr)
        raise SystemExit(2)
