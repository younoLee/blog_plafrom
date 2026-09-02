#!/usr/bin/env python3
"""프론트엔드 번들 크기 예산. 넘으면 CI를 빨간불로 만든다.

**왜 필요한가 (2026-09-02 공백 검사).** 메인 번들이 469KB에서 528KB로 자랐는데
그걸 재는 곳이 저장소에 하나도 없었다. 의존성 하나를 추가하면 수십 KB가 조용히
붙고, 다음 사람은 '원래 이 정도였나' 하고 넘어간다. 이 저장소가 반복해 배운 모양이다
(`docs/gap-inspection-20260811.md`: 규칙을 쓴 다음에는 몇 개가 걸리는지 반드시 센다).

이 사이트는 EC2가 대부분 꺼져 있어서 **첫 화면이 정적 자산으로만 그려진다.**
그 자산이 커지는 것은 서버가 꺼진 동안의 유일한 체감 성능 저하다.

**한도를 어떻게 정했나.** 지금 값(2026-09-02 실측)에 여유를 얹은 값이다.
'목표'가 아니라 '조용히 넘지 말 것'이다. 줄이는 일은 별도 과제이고, 이 검사는
줄이라고 요구하지 않는다. 다만 넘을 때는 사람이 값을 올리는 커밋을 남기게 한다.
그 커밋이 곧 "이만큼 커지는 걸 알고 받아들였다"는 기록이다.

  · index-*.js  528,447 B → 한도 580,000 B (약 10% 여유)
  · index-*.css  93,036 B → 한도 110,000 B
  · 합계        647,126 B → 한도 720,000 B

압축 후 크기가 아니라 **원본 바이트**를 잰다. CloudFront가 gzip/brotli로 줄여
보내지만, 파싱·실행 비용은 압축을 푼 뒤의 크기에 붙고 저사양 기기에서 그게 더 아프다.
(brotli 사전압축은 일부러 안 한다 — S3 정적 호스팅은 Accept-Encoding에 따라 다른
표현을 못 골라서, br을 안 받는 클라이언트가 깨진 바이트를 받는다.)

사용:
  python3 scripts/check_bundle_size.py            # 검사 (dist가 있어야 한다)
  python3 scripts/check_bundle_size.py --measure  # 지금 크기만 출력
  python3 scripts/check_bundle_size.py --selftest # 검사기 자신이 동작하는가
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "frontend" / "dist"

# (glob, 한도 바이트, 설명). glob이 여러 파일에 걸리면 합계를 잰다.
BUDGETS = [
    ("index-*.js", 580_000, "메인 JS 번들"),
    ("index-*.css", 110_000, "메인 CSS"),
]
TOTAL_BUDGET = 720_000  # 위 둘 + 나머지 청크(PaymentPage·devlog-filter·sw 등) 합계


def measure(dist: Path) -> tuple[list[tuple[str, int, int, str]], int]:
    """(glob, 실측, 한도, 설명) 목록과 전체 합계를 돌려준다."""
    rows = []
    for pattern, limit, label in BUDGETS:
        hits = sorted(dist.glob(pattern))
        # **0개를 통과로 읽지 않는다.** 산출물 이름이 바뀌면(assetsDir·해시 규칙 변경)
        # glob이 조용히 0개가 되고 검사는 "0바이트, 한도 이하"로 초록이 된다.
        # 이 저장소가 세 번 당한 '대상 0개인데 통과' 그대로다. 음수로 표시해 아래에서 잡는다.
        size = sum(p.stat().st_size for p in hits) if hits else -1
        rows.append((pattern, size, limit, label))
    total = sum(p.stat().st_size for p in dist.glob("*.js")) + sum(
        p.stat().st_size for p in dist.glob("*.css")
    )
    return rows, total


def check(dist: Path) -> int:
    if not dist.is_dir():
        print(f"❌ {dist} 가 없다. 먼저 `npm run build` 를 돌려라.", file=sys.stderr)
        return 1

    rows, total = measure(dist)
    bad = 0
    for pattern, size, limit, label in rows:
        if size < 0:
            print(f"❌ {label}: `{pattern}` 에 걸리는 파일이 0개다. 산출물 이름이 바뀌었는지 확인해라.")
            bad += 1
        elif size > limit:
            over = size - limit
            print(f"❌ {label}: {size:,} B (한도 {limit:,} B, {over:,} B 초과)")
            bad += 1
        else:
            print(f"✅ {label}: {size:,} B / {limit:,} B")

    if total > TOTAL_BUDGET:
        print(f"❌ js+css 합계: {total:,} B (한도 {TOTAL_BUDGET:,} B)")
        bad += 1
    else:
        print(f"✅ js+css 합계: {total:,} B / {TOTAL_BUDGET:,} B")

    if bad:
        print()
        print("번들이 예산을 넘었다. 둘 중 하나를 해라 — 줄이거나, 한도를 올리는 커밋을 남기거나.")
        print("한도를 올릴 거면 이 파일의 BUDGETS 주석에 '왜 커졌는지'를 같이 적어라.")
        return 1
    return 0


def selftest() -> int:
    """검사기가 실제로 잡는가. 한도가 통째로 빠져도 초록이 되는 걸 막는다."""
    import tempfile

    ok = True
    with tempfile.TemporaryDirectory() as td:
        fake = Path(td)
        # ① 한도를 넘는 파일 → 반드시 실패해야 한다
        (fake / "index-aaaaaaaa.js").write_bytes(b"x" * (580_000 + 1))
        (fake / "index-aaaaaaaa.css").write_bytes(b"x" * 10)
        rows, _ = measure(fake)
        if rows[0][1] <= rows[0][2]:
            print("❌ selftest: 한도 초과를 초과로 안 읽는다")
            ok = False

        # ② glob에 안 걸리는 이름 → 0개를 통과로 읽으면 안 된다
        empty = Path(td) / "empty"
        empty.mkdir()
        (empty / "main-bbbb.js").write_bytes(b"x" * 10)
        rows2, _ = measure(empty)
        if rows2[0][1] != -1:
            print("❌ selftest: 대상 0개를 '0바이트 통과'로 읽는다")
            ok = False

    if not BUDGETS:
        print("❌ selftest: BUDGETS 가 비었다. 검사가 아무것도 안 재고 있다")
        ok = False

    print("✅ selftest 통과" if ok else "❌ selftest 실패")
    return 0 if ok else 1


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "--selftest":
        sys.exit(selftest())
    if arg == "--measure":
        rows, total = measure(DIST)
        for pattern, size, limit, label in rows:
            print(f"{label:12} {pattern:16} {size:>10,} B (한도 {limit:,})")
        print(f"{'합계':12} {'*.js + *.css':16} {total:>10,} B (한도 {TOTAL_BUDGET:,})")
        sys.exit(0)
    sys.exit(check(DIST))
