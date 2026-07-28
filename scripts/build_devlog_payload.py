"""content/devlog/*.md → publish_devlogs.py가 먹는 payload(JSON).

왜 스크립트인가 — 이 JSON은 그동안 발행할 때마다 손으로 만들었다. 그래서 매번
'H1을 빼야 한다'(publish_devlogs가 제목을 따로 받는다)와 'series를 넣어야 한다'
(빠뜨리면 글은 보이는데 연재 네비가 null이 된다 — 2026-07-20에 겪음)를 기억에
의존했다. 기억은 두 번에 한 번 틀린다.

제목·태그는 devlog_to_markdown.POSTS가 유일한 출처다. 마크다운의 H1을 파싱하지
않는 이유: 같은 값이 두 군데 살면 언젠가 갈라지고, 그때 어느 쪽이 맞는지 알 수 없다.

사용:
  python scripts/build_devlog_payload.py                  # 전체 → /tmp/devlog_posts.json
  python scripts/build_devlog_payload.py 2026-07-22 2026-07-24 2026-07-27
  python scripts/build_devlog_payload.py -o out.json 2026-07-27

python-docx가 필요하다(devlog_to_markdown을 import하므로). 로컬 파이썬에 없으면
변환할 때와 같은 컨테이너에서 돌린다:
  docker run --rm -v "$PWD":/work -w /work python:3.12-slim \
      sh -c "pip install -q python-docx && python scripts/build_devlog_payload.py"
"""

import json
import sys
from pathlib import Path

from devlog_to_markdown import OUT_DIR, POSTS

SERIES = "블로그 만들기"


def build(dates: list[str]) -> list[dict]:
    items = []
    for date in dates:
        if date not in POSTS:
            sys.exit(f"{date}: devlog_to_markdown.POSTS에 제목·태그가 없습니다.")
        md = OUT_DIR / f"{date}.md"
        if not md.exists():
            sys.exit(f"{md} 가 없습니다. 먼저 devlog_to_markdown.py 를 돌리세요.")

        title, tags = POSTS[date]
        text = md.read_text(encoding="utf-8")

        # H1은 제목이 이미 들고 있다. 본문에 남기면 글 화면에 제목이 두 번 나온다.
        body = text.split("\n", 1)[1] if text.startswith("# ") else text
        items.append(
            {
                "date": date,
                "title": title,
                "content": body.strip(),
                "tags": tags,
                "series": SERIES,
            }
        )
    return items


def main() -> None:
    args = sys.argv[1:]
    out = Path("/tmp/devlog_posts.json")
    if "-o" in args:
        i = args.index("-o")
        if i + 1 >= len(args):
            sys.exit("-o 뒤에 출력 경로가 없습니다.")  # IndexError 대신 사람이 읽는 말로
        out = Path(args[i + 1])
        del args[i : i + 2]

    dates = args or sorted(POSTS)
    items = build(dates)
    out.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

    for it in items:
        print(f"{it['date']}  {len(it['content']):>6,}자  {it['title']}")
    print(f"\n→ {out}  ({out.stat().st_size:,} bytes, {len(items)}편)")


if __name__ == "__main__":
    main()
