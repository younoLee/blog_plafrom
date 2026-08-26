#!/usr/bin/env python3
"""BYOK 키 재암호화 — `LLM_ENCRYPTION_KEY`를 교체할 때 옛 암호문을 새 키로 옮긴다.

왜 이 파일이 생겼는가 (2026-08-26) —
`docs/incident-response.md`가 2026-07-27에 `LLM_ENCRYPTION_KEY`를 **일부러 안 바꿨다**고
적으면서 이유를 "재암호화 계획 없이는 손대지 않는다"로 남겼다. 그 계획이 4주 동안
안 생겼고, 그래서 이 키는 **유출돼도 교체할 수 없는 시크릿**이었다. 절차가 없는 게
아니라 절차를 만들 도구가 없었던 것이다. IR 훈련은 절차를 검증하는 것이지 발명하는
것이 아니라, 도구가 없으면 그 항목은 훈련에서 통째로 빠진다.

순서가 안전에 직결된다 — **재암호화가 폐기보다 먼저다.**
  ① 새 키 생성 → ② 이 스크립트로 재암호화 → ③ .env 교체 → ④ 검증 → ⑤ 옛 키 폐기
뒤집으면 `llm_credentials`가 통째로 죽는다. 이 키는 자격증명이 아니라 **데이터를 푸는
열쇠**라, 잃으면 데이터가 같이 죽는 부류다(RECOVERY.md 시나리오 D).

MultiFernet.rotate를 쓴다. 옛 키로 풀어 새 키로 다시 잠그는 것을 한 호출로 하고,
**이미 새 키로 잠긴 행은 그대로 통과**시킨다 — 중간에 죽어서 다시 돌려도 안전하다.

사용:
    scripts/reencrypt_llm_keys.py --dry-run --old <OLD> --new <NEW>
    scripts/reencrypt_llm_keys.py --old <OLD> --new <NEW>
    OLD_KEY=... NEW_KEY=... scripts/reencrypt_llm_keys.py    # 환경변수로도 받는다

옛 에스크로 사본을 지우지 말 것. 일부 행이 실패하면 그 행은 옛 키로만 풀린다.
평문은 **어디에도 출력하지 않는다.** 성공/실패와 행 수만 본다.
"""
import argparse
import os
import sys

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from sqlalchemy import create_engine, text


def _mask(k: str) -> str:
    """키를 로그에 남길 때 쓰는 형태. 앞 6자만."""
    return f"{k[:6]}…({len(k)}자)" if k else "(빈값)"


def main() -> int:
    ap = argparse.ArgumentParser(description="BYOK 키 재암호화")
    ap.add_argument("--old", default=os.environ.get("OLD_KEY", ""), help="현재 LLM_ENCRYPTION_KEY")
    ap.add_argument("--new", default=os.environ.get("NEW_KEY", ""), help="새 LLM_ENCRYPTION_KEY")
    ap.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", ""),
        help="기본값은 환경변수 DATABASE_URL",
    )
    ap.add_argument("--dry-run", action="store_true", help="세기만 하고 쓰지 않는다")
    args = ap.parse_args()

    if not args.old or not args.new:
        print("--old 와 --new 가 모두 필요하다 (또는 OLD_KEY/NEW_KEY 환경변수)", file=sys.stderr)
        return 2
    if args.old == args.new:
        print("옛 키와 새 키가 같다 — 할 일이 없다", file=sys.stderr)
        return 2
    if not args.database_url:
        print("DATABASE_URL 이 필요하다", file=sys.stderr)
        return 2

    try:
        old_f = Fernet(args.old.encode())
        new_f = Fernet(args.new.encode())
    except (ValueError, TypeError) as e:
        # 여기서 죽는 게 낫다. 잘못된 키로 진행하면 전 행이 실패로 찍힌다.
        print(f"키 형식이 Fernet 이 아니다: {e}", file=sys.stderr)
        return 2

    # 순서가 중요하다: MultiFernet 은 **앞에서부터** 복호화를 시도하고, rotate 는 항상
    # 맨 앞 키로 다시 잠근다. 그래서 [새, 옛] 이어야 '이미 새 키로 잠긴 행'도 통과한다.
    rotator = MultiFernet([new_f, old_f])

    engine = create_engine(args.database_url)
    print(f"  옛 키 {_mask(args.old)} → 새 키 {_mask(args.new)}")
    print(f"  모드: {'dry-run(쓰지 않음)' if args.dry_run else '실행'}")

    ok = skipped = failed = 0
    failures: list[tuple[int, int, str]] = []

    with engine.begin() as conn:
        rows = conn.execute(
            text("select id, user_id, provider, encrypted_key from llm_credentials order by id")
        ).all()
        print(f"  대상 {len(rows)}행")
        if not rows:
            # 0행은 '할 일 없음'이지 '성공'이 아니다. 복원 훈련의 카나리아와 같은 이유로
            # 이 구분을 흐리면, 키가 어긋난 날에도 이 도구가 조용히 초록으로 끝난다.
            print("  llm_credentials 가 0행이다 — 재암호화할 것이 없다(검증된 것도 없다).")
            return 0

        by_provider: dict[str, int] = {}
        for row in rows:
            by_provider[row.provider] = by_provider.get(row.provider, 0) + 1

        for row in rows:
            token = row.encrypted_key.encode()
            # 이미 새 키로 잠겨 있는가? 그러면 건드리지 않는다(재실행 안전).
            try:
                new_f.decrypt(token)
                skipped += 1
                continue
            except InvalidToken:
                pass
            try:
                rotated = rotator.rotate(token).decode()
            except InvalidToken:
                # 옛 키로도 새 키로도 안 풀린다 = 이 행은 **또 다른 세대의 키**로 잠겨 있다.
                failed += 1
                failures.append((row.id, row.user_id, row.provider))
                continue
            if not args.dry_run:
                conn.execute(
                    text("update llm_credentials set encrypted_key = :k where id = :i"),
                    {"k": rotated, "i": row.id},
                )
            ok += 1

        if args.dry_run:
            # begin() 블록은 정상 종료 시 커밋한다. dry-run 에서는 아무것도 안 썼으므로
            # 커밋해도 무해하지만, 의도를 코드로 남긴다.
            conn.rollback()

    print(f"  provider 분포: {by_provider}")
    print(f"  재암호화 {ok} · 이미 새 키 {skipped} · 실패 {failed}")
    if failures:
        print("  실패 행 (id, user_id, provider) — 옛 에스크로 사본에서 그 세대 키를 찾아야 한다:")
        for fid, uid, prov in failures:
            print(f"    {fid} {uid} {prov}")
        return 1
    if args.dry_run:
        print("  dry-run 이라 쓰지 않았다. 같은 인자에서 --dry-run 을 빼면 실행된다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
