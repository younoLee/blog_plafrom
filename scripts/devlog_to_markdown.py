"""개발일지(.docx)를 블로그 글 마크다운으로 변환.

개발일지는 make_devlog_*.py가 python-docx로 만든 것이라 문단 구조가 일정하다.
그 구조를 마크다운으로 되돌린다:

  Title "블로그 개발일지"        → 버림(제목은 POSTS 맵에서 지정)
  표지의 작성일/스택/주제 줄     → 버림(제목·태그로 대체). '대상:'만 인용문 리드로 남김
  Heading 1 "3. 관리자 대시보드" → "## 3. 관리자 대시보드"  (Heading 2 → ###)
  List Bullet                    → "- "
  🔎 비유 / 🛠 전문가 노트        → 인용문(>)
  field("라벨", "내용")          → "**라벨** — 내용"
  그 외 문단                     → 그대로

제목·태그를 자동 추출하지 않고 POSTS에 손으로 적는 이유: 초기 3편(06-21·06-22·06-24)은
표지 형식이 달라 '주제:' 줄이 없고, 있는 편들도 주제 줄이 제목으로 쓰기엔 너무 길다.

사용:
  python scripts/devlog_to_markdown.py                 # 전체 → content/devlog/*.md
  python scripts/devlog_to_markdown.py 2026-07-12      # 한 편만 stdout으로 (미리보기)
"""

import re
import sys
from pathlib import Path

from docx import Document

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "content" / "devlog"

# 날짜 → (블로그 글 제목, 태그). 태그는 글당 10개·개당 30자 제한(schemas/post.py).
POSTS: dict[str, tuple[str, list[str]]] = {
    "2026-06-21": ("블로그 만들기 #1 — 빈 폴더에서 풀스택 블로그 뼈대까지",
                   ["개발일지", "FastAPI", "React", "Docker", "PostgreSQL"]),
    "2026-06-22": ("블로그 만들기 #2 — 통합 포털 · 서비스 상태 · AI 글 초안",
                   ["개발일지", "FastAPI", "React", "Docker", "AI"]),
    "2026-06-24": ("블로그 만들기 #3 — AWS 풀스택 배포 대장정",
                   ["개발일지", "AWS", "배포", "EC2", "RDS", "CloudFront"]),
    "2026-06-25": ("블로그 만들기 #4 — 계정 권한 시스템 + AWS 배포 + 보안 강화",
                   ["개발일지", "보안", "인증", "AWS"]),
    "2026-06-26": ("블로그 만들기 #5 — S3 이미지 이전 · 구독 완결 · 보안 점검 5회",
                   ["개발일지", "보안", "AWS", "S3"]),
    "2026-06-27": ("블로그 만들기 #6 — 남은 보안 구멍 마무리 + AI 초안 보안",
                   ["개발일지", "보안", "AI"]),
    "2026-06-28": ("블로그 만들기 #7 — AI 초안 3종 보강 + 모바일 화면 정리",
                   ["개발일지", "AI", "프론트엔드"]),
    "2026-06-29": ("블로그 만들기 #8 — 검은 화면 버그, 추측 말고 측정으로",
                   ["개발일지", "디버깅", "프론트엔드"]),
    "2026-06-30": ("블로그 만들기 #9 — 또 검은 화면, 이번엔 진짜 크래시 + 전체 코드 감사",
                   ["개발일지", "디버깅", "코드리뷰", "프론트엔드"]),
    "2026-07-02": ("블로그 만들기 #10 — 내 사이트 침투점검하고 구멍 막기",
                   ["개발일지", "보안", "DoS", "AWS"]),
    "2026-07-04": ("블로그 만들기 #11 — 초라한 블로그 진단 + 본문 크기 DoS 방어",
                   ["개발일지", "프론트엔드", "DoS", "보안"]),
    "2026-07-11": ("블로그 만들기 #12 — 코드 하이라이팅 · 태그 · SQL 인젝션 점검",
                   ["개발일지", "보안", "프론트엔드", "PostgreSQL"]),
    "2026-07-12": ("블로그 만들기 #13 — DoS 마무리 · 관리자 대시보드 · WAF 비용",
                   ["개발일지", "AWS", "비용", "DoS"]),
    "2026-07-15": ("블로그 만들기 #14 — 고정 IP · 구독 UI 통합 · 토스 결제",
                   ["개발일지", "AWS", "결제", "보안"]),
    "2026-07-17": ("블로그 만들기 #15 — 글 채우기 · 검색 · 그리고 \"$0\"의 정체",
                   ["개발일지", "AWS", "비용", "PostgreSQL", "보안"]),
}

# 본문에서 이 접두사로 시작하는 문단은 인용문으로 뽑는다.
CALLOUTS = ("🔎 비유", "🛠 전문가 노트")

# 표지에서 버릴 메타 줄(제목·태그가 대신한다).
DROP_META = ("작성일:", "날짜:", "스택:", "목표:", "주제:", "오늘 주제:", "오늘의 주제:")


def _is_bullet(para) -> bool:
    return para.style.name in ("List Bullet", "List Bullet 2", "List Number")


def _heading_level(para) -> int | None:
    """Heading 1 → 1. 제목(Title)은 0. 본문이면 None."""
    if para.style.name in ("Title", "Heading 0"):
        return 0
    m = re.match(r"^Heading (\d+)$", para.style.name)
    return int(m.group(1)) if m else None


def _callout(text: str) -> str | None:
    for mark in CALLOUTS:
        if text.startswith(mark):
            return f"> **{mark}** {text[len(mark):].strip()}"
    return None


def _field(para) -> str | None:
    """field()로 만든 문단(첫 run이 bold 라벨 + 나머지가 내용)이면 '**라벨** — 내용'.

    문단 전체가 bold면 단순 강조 문단이므로 field가 아니다.
    """
    runs = [r for r in para.runs if r.text.strip()]
    if len(runs) < 2 or not runs[0].bold or all(r.bold for r in runs):
        return None
    label = runs[0].text.strip()
    body = "".join(r.text for r in runs[1:]).strip()
    return f"**{label}** — {body}" if label and body else None


def _cover_line(text: str) -> str | None:
    """표지 문단 → 남길 마크다운(없으면 None).

    '대상:'은 이 글이 누구를 위한 글인지라 리드 인용문으로 남기고,
    나머지 메타(작성일·스택·주제…)와 '2026-06-22 · 스택: …' 형태는 버린다.
    """
    if text.startswith("대상:"):
        return f"> {text[3:].strip()}"
    if any(text.startswith(k) for k in DROP_META):
        return None
    if re.match(r"^\d{4}-\d{2}-\d{2}\s*[·・]", text):  # "2026-06-22 · 스택: …"
        return None
    return text  # 그 외 표지 문단(리드 설명 등)은 본문으로 살린다


def convert(path: Path) -> tuple[str, str, list[str]]:
    """docx → (제목, 마크다운 본문, 태그)."""
    doc = Document(str(path))
    date = path.stem.split("_")[-1]
    if date not in POSTS:
        raise SystemExit(f"{date}의 제목·태그가 POSTS에 없습니다. 스크립트에 추가하세요.")
    title, tags = POSTS[date]

    blocks: list[str] = []
    seen_heading = False

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue

        level = _heading_level(para)
        if level == 0:
            continue  # 표지 제목은 버린다

        if level is not None:
            seen_heading = True
            blocks.append(f"{'#' * (level + 1)} {text}")
            continue

        if not seen_heading:  # 아직 표지 영역
            line = _cover_line(text)
            if line:
                blocks.append(line)
            continue

        callout = _callout(text)
        if callout:
            blocks.append(callout)
            continue

        field = _field(para)
        if field:
            blocks.append(field)
            continue

        if _is_bullet(para):
            # 연속된 불릿은 한 블록으로 묶어야 마크다운 목록이 끊기지 않는다
            if blocks and blocks[-1].startswith("- "):
                blocks[-1] += f"\n- {text}"
            else:
                blocks.append(f"- {text}")
            continue

        blocks.append(text)

    body = "\n\n".join(blocks)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return title, body, tags


def main() -> None:
    files = sorted(ROOT.glob("블로그_개발일지_*.docx"))
    if not files:
        sys.exit("개발일지 .docx를 찾지 못했습니다.")

    if len(sys.argv) > 1:
        target = next((f for f in files if sys.argv[1] in f.name), None)
        if not target:
            sys.exit(f"{sys.argv[1]} 개발일지를 찾지 못했습니다.")
        title, body, tags = convert(target)
        print(f"제목: {title}\n태그: {tags}\n글자수: {len(body):,}\n{'─' * 60}\n{body}")
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for f in files:
        title, body, tags = convert(f)
        date = f.stem.split("_")[-1]
        (OUT_DIR / f"{date}.md").write_text(f"# {title}\n\n{body}\n", encoding="utf-8")
        print(f"{date}  {len(body):>6,}자  {title}")


if __name__ == "__main__":
    main()
