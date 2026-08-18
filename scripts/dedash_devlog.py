#!/usr/bin/env python3
"""발행된 개발일지에서 em 대시(—)를 줄인다. **서식만 바꾸고 내용은 안 건드린다.**

왜 '다시 쓰기'가 아니라 이건가 (2026-08-18)
--------------------------------------------
사람 글과 재보니 이 블로그는 em 대시를 1만 자당 71.5개 썼다(사람 글 1.4개, 51배).
그런데 그걸 고치자고 33편 24만 자를 **다시 쓰면** 두 가지를 잃는다:

  · 이 글들은 터미널 출력과 숫자를 그대로 실은 **기록**이다. 문장을 다시 만들면
    그 자리에 없던 사실이 섞여 들어가고, 24만 자를 사람이 검수할 방법이 없다.
  · 발행된 글이라 되돌리면 기록 자체가 흔들린다.

그래서 규칙 기반으로 **부호만** 바꾼다. diff가 기계적이라 눈으로 검토할 수 있고,
숫자·명령·경로는 한 글자도 안 변한다. 코드블록·인라인 코드·링크는 아예 안 건드린다.

바꾸는 규칙
-----------
  1) 문장 종결어미 뒤   `…같다 — 집 공인 IP가`      → `…같다. 집 공인 IP가`
  2) 라벨 뒤            `**결과 숫자** — sitemap에`   → `**결과 숫자**: sitemap에`
  3) 나머지 삽입구      `A — B` (한쪽만)             → 그대로 둔다

3)을 그대로 두는 이유: 진짜 삽입구는 em 대시가 맞는 자리다. 전부 없애는 게 목표가
아니라 **51배를 사람 수준으로 되돌리는 것**이 목표다. 애매한 건 손대지 않는 쪽이
안전하고, 애매함을 기계가 판단하면 문장이 이상해진다.

사용:
  python3 scripts/dedash_devlog.py --dry content/devlog/2026-08-17.md   # 미리보기
  python3 scripts/dedash_devlog.py content/devlog/*.md                  # 적용
"""
import argparse
import pathlib
import re

# 한국어 문장 종결로 볼 어미. 뒤에 오는 em 대시는 문장 경계일 가능성이 높다.
ENDINGS = "다요음임함됨함까랑"

# ① 종결어미 + 공백 + — + 공백 → 마침표. 단 **오른쪽도 문장일 때만.**
#
# 파일럿에서 이렇게 깨졌다:
#   전: 이 사이트는 상태가 두 개다 — **서버가 꺼진 평상시**와 **켜진 날**.
#   후: 이 사이트는 상태가 두 개다. **서버가 꺼진 평상시**와 **켜진 날**.   ← 뒤가 문장이 아니다
# 오른쪽이 명사구면 그건 진짜 삽입구라 em 대시가 맞는 자리다. 그래서 대시 뒤부터
# 다음 마침표까지를 미리 보고, 그 끝이 종결어미일 때만 끊는다.
SENTENCE = re.compile(
    rf"(?<=[{ENDINGS}])\s+—\s+(?=[^\n—.]*[{ENDINGS}][.\)\]'\"]*(?:\.|$))"
)
# ② 줄머리의 짧은 라벨(굵게 포함) 뒤의 — → 콜론
LABEL = re.compile(r"^(\s*(?:[-*]\s+)?(?:\*\*[^*\n]{1,24}\*\*|[^\s—\n]{1,20}))\s+—\s+", re.M)


def split_protected(text: str):
    """코드블록·인라인 코드·링크 주소를 건드리지 않게 잘라 낸다.

    (조각, 바꿔도 되는가) 목록을 돌려준다. 정규식 하나로 본문 전체를 훑으면
    ``` 안의 `--force -- foo` 같은 것까지 바뀐다.
    """
    pattern = re.compile(r"(?s)(```.*?```|`[^`\n]*`|\]\([^)\n]*\))")
    out, last = [], 0
    for m in pattern.finditer(text):
        if m.start() > last:
            out.append((text[last : m.start()], True))
        out.append((m.group(0), False))
        last = m.end()
    out.append((text[last:], True))
    return out


# 소제목 줄은 **통째로 건드리지 않는다.**
#
# `## 3. 검사를 두 번 돌렸다 — 끈 채로 한 번`을 마침표로 끊으면 제목 글자가 바뀌고,
# 그러면 rehype-slug가 만드는 id가 바뀐다 = 목차 앵커와 이미 나간 링크·북마크가 죽는다.
# 같은 날 오전에 그 앵커들을 고쳐놨는데 여기서 다시 깨뜨릴 수는 없다.
HEADING = re.compile(r"^\s{0,3}#{1,6}\s")


def convert_line(line: str) -> tuple[str, int]:
    if HEADING.match(line):
        return line, 0
    line, a = LABEL.subn(r"\1: ", line)
    line, b = SENTENCE.subn(". ", line)
    return line, a + b


def convert(text: str) -> tuple[str, int]:
    """바꾼 텍스트와 바꾼 개수."""
    pieces, n = [], 0
    for chunk, editable in split_protected(text):
        if editable:
            lines = chunk.split("\n")
            for i, ln in enumerate(lines):
                lines[i], c = convert_line(ln)
                n += c
            chunk = "\n".join(lines)
        pieces.append(chunk)
    return "".join(pieces), n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--dry", action="store_true", help="파일을 안 고치고 바뀔 줄만 보여준다")
    ap.add_argument("--sample", type=int, default=0, help="--dry 때 보여줄 예시 줄 수")
    args = ap.parse_args()

    total_before = total_after = changed = 0
    samples: list[tuple[str, str]] = []
    for f in args.files:
        p = pathlib.Path(f)
        src = p.read_text(encoding="utf-8")
        dst, n = convert(src)
        before = src.count("—")
        after = dst.count("—")
        total_before += before
        total_after += after
        changed += n
        if n and args.sample:
            for a, b in zip(src.splitlines(), dst.splitlines()):
                if a != b and len(samples) < args.sample:
                    samples.append((a.strip(), b.strip()))
        if not args.dry and n:
            p.write_text(dst, encoding="utf-8")
        print(f"  {p.name}  em대시 {before} → {after}  (바꾼 자리 {n})")

    for a, b in samples:
        print(f"\n  전: {a[:150]}\n  후: {b[:150]}")
    print(f"\n  합계 em대시 {total_before} → {total_after} · 바꾼 자리 {changed}")
    if args.dry:
        print("  (--dry 라 파일은 안 고쳤다)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
