#!/usr/bin/env python3
"""계정을 직접 만든다 — 가입이 '초대제'로 닫혀 있어서 self-register 경로가 없기 때문.

두 가지 용도:
  1) 초대: 아는 사람에게 writer 계정을 발급 (email_verified=True로 바로 로그인 가능)
  2) 데모: 포트폴리오 방문자용 '체험 계정' (프론트의 '체험 계정으로 둘러보기' 버튼이 이 계정으로 로그인)

가입 라우터(auth.py)를 안 거치므로 인증메일·SES가 필요 없다 — 그래서 샌드박스여도 동작한다.
admin 승격은 여전히 DB에서만(이 스크립트는 pending/writer까지만; --role admin은 명시해야 함).

실행 (프로덕션은 사용자가 직접 — 규칙7):
  # 로컬 도커
  docker compose exec backend python scripts/create_user.py demo@example.com --demo
  # 임의 계정
  docker compose exec backend python scripts/create_user.py invite@you.com --role writer --password 's3cret!!'
  # 비번 생략 시 안전한 랜덤 비번을 만들어 출력한다
"""
from __future__ import annotations

import argparse
import os
import secrets
import sys

# 이 파일은 backend/scripts/ 아래에 있다. backend 루트를 path에 넣어야 `app.*`를 import 할 수 있다
# (cwd가 어디든 동작하게 — 컨테이너에선 /app, 로컬에선 backend/).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models.user import User  # noqa: E402

ALLOWED_ROLES = ("pending", "writer", "admin")


def main() -> int:
    ap = argparse.ArgumentParser(description="초대/데모 계정을 DB에 직접 생성한다")
    ap.add_argument("email")
    ap.add_argument(
        "--role",
        default="writer",
        choices=ALLOWED_ROLES,
        help="기본 writer(글쓰기 가능). 데모/초대는 대개 writer면 충분",
    )
    ap.add_argument(
        "--password",
        help="생략하면 안전한 랜덤 비번을 생성해 출력한다",
    )
    ap.add_argument(
        "--demo",
        action="store_true",
        help="데모 계정 프리셋: 비번 미지정 시 'demo1234!'를 쓴다(공개 데모라 알려진 비번이 목적)",
    )
    ap.add_argument(
        "--update-if-exists",
        action="store_true",
        help="이미 있는 이메일이면 비번·role을 덮어쓴다(없으면 에러). 데모 비번 재설정에 유용",
    )
    args = ap.parse_args()

    password = args.password or ("demo1234!" if args.demo else secrets.token_urlsafe(12))

    db = SessionLocal()
    try:
        existing = db.scalar(select(User).where(User.email == args.email))
        if existing is not None:
            if not args.update_if_exists:
                print(
                    f"! 이미 존재하는 계정: {args.email} (role={existing.role}). "
                    "비번/role을 바꾸려면 --update-if-exists 를 붙여라.",
                    file=sys.stderr,
                )
                return 1
            existing.hashed_password = hash_password(password)
            existing.role = args.role
            existing.email_verified = True
            existing.token_version += 1  # 기존 세션/링크 무효화
            db.commit()
            action = "업데이트"
            user = existing
        else:
            user = User(
                email=args.email,
                hashed_password=hash_password(password),
                role=args.role,
                email_verified=True,  # 인증메일 없이 바로 로그인 가능하게
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            action = "생성"

        print(f"✓ 계정 {action} 완료")
        print(f"  id       : {user.id}")
        print(f"  email    : {user.email}")
        print(f"  role     : {user.role}")
        print(f"  password : {password}")
        if not args.password and not args.demo:
            print("  (위 랜덤 비번을 초대 대상에게 안전한 채널로 전달하고, 첫 로그인 후 바꾸게 안내해라)")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
