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
    "2026-07-18": ("블로그 만들기 #16 — RDS 들어내기 · 테스트 0→103 · 구독을 신청·승인제로",
                   ["개발일지", "AWS", "테스트", "CI", "기능개발"]),
    "2026-07-20": ("블로그 만들기 #17 — \"설정했다\"와 \"동작한다\"는 다르다 (백업이 안 돌고 있었다)",
                   ["개발일지", "보안", "운영", "AWS", "테스트"]),
    "2026-07-22": ("블로그 만들기 #18 — 내가 만든 안전장치를 검사했다 (복원 훈련의 구멍 13개)",
                   ["개발일지", "백업", "복구", "모니터링", "보안"]),
    "2026-07-24": ("블로그 만들기 #19 — ECS 마이그레이션: 짓기보다 증명하기가 어려웠다",
                   ["개발일지", "ECS", "Fargate", "AWS", "terraform"]),
    "2026-07-27": ("블로그 만들기 #20 — 재보지 않으면 모르는 것들 (DR 게임데이 · IR 훈련)",
                   ["개발일지", "재해복구", "장애대응", "보안", "AWS"]),
    "2026-07-28": ("블로그 만들기 #21 — 초록불이 '확인했다'는 뜻이 아닐 때",
                   ["개발일지", "보안", "CI", "카오스엔지니어링", "운영"]),
    "2026-07-30": ("블로그 만들기 #22 — 고쳤다고 '기억하는' 것과 실제로 고쳐진 것",
                   ["개발일지", "비용", "AWS", "코드리뷰", "운영"]),
    "2026-07-31": ("블로그 만들기 #23 — 적어놓은 것과 실제로 돌고 있는 것",
                   ["개발일지", "SES", "AWS", "배포", "운영"]),
    "2026-08-03": ("블로그 만들기 #24 — 막는 것과, 뚫렸는지 아는 것은 다른 일이다",
                   ["개발일지", "보안", "AI", "프롬프트인젝션"]),
    "2026-08-04": ("블로그 만들기 #25 — 빨간불 네 개, 처방이 네 개 다 달랐다",
                   ["개발일지", "운영", "CI", "배포", "AWS"]),
    "2026-08-07": ("블로그 만들기 #26 — 초록불이 세 번 거짓말했다",
                   ["개발일지", "CI", "테스트", "배포", "WebPush"]),
    "2026-08-09": ("블로그 만들기 #27 — '안 한 일' 목록이 먼저 썩는다",
                   ["개발일지", "운영", "문서", "모니터링", "AWS"]),
    "2026-08-10": ("블로그 만들기 #28 — 고친 자리 옆에 안 쓸린 입구가 있다",
                   ["개발일지", "보안", "성능", "코드리뷰", "AWS"]),
    # #26이 "초록불이 세 번 거짓말했다"라 제목이 겹치지 않게 골랐다. #26은 '초록인데 틀렸다'였고
    # 이번은 그 한 겹 아래 — **애초에 보지 않아서 초록이었다**는 이야기다.
    "2026-08-11": ("블로그 만들기 #29 — 검사가 실패하지 않은 것과 통과한 것은 다르다",
                   ["개발일지", "코드리뷰", "테스트", "모니터링", "타입검사"]),
}

# 본문에서 이 접두사로 시작하는 문단은 인용문으로 뽑는다.
CALLOUTS = ("🔎 비유", "🛠 전문가 노트")

# 표지에서 버릴 메타 줄(제목·태그가 대신한다).
DROP_META = ("작성일:", "날짜:", "스택:", "목표:", "주제:", "오늘 주제:", "오늘의 주제:")


def _is_mono(para) -> bool:
    """터미널 출력 문단인가 — 실행이 하나라도 고정폭 글꼴이면 그렇게 본다.

    make_devlog의 ev()가 Consolas로 찍는다. 캡션("▶ 실제 출력 — …")은 굵은 본문 글꼴이라
    여기 안 걸리고, 코드블록 위에 라벨로 남는다.
    """
    return any(r.font.name == "Consolas" for r in para.runs)


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


# ── 스타일이 평탄화된 회차 되살리기 ────────────────────────────────────────
# 2026-07-24 편은 Heading·List Bullet이 전부 Normal로 저장돼 있다(같은 make_devlog가
# add_heading을 쓰는데도 그렇다 — 파일이 한 번 다른 도구를 거친 것으로 보인다).
# 그대로 변환하면 8개 절이 전부 사라져 제목 1개짜리 마크다운이 나온다.
#
# 되살리는 조건을 **문서 단위**로 건다: "이 문서에 Heading 스타일이 하나도 없을 때만".
# 문단 단위로 걸면 스타일이 멀쩡한 회차에서 본문 중 "3. 세 번째 이유는 …" 같은 문장이
# 절 제목으로 잘못 승격된다. 평탄화된 문서는 어차피 잃을 구조가 없으니 안전하다.
FLAT_HEADING = re.compile(r"^(\d+)\.(\d+)?\s+\S")
FLAT_BULLET = re.compile(r"^[•·]\s+")
FLAT_TITLE = "블로그 개발일지"  # Title 스타일이 날아가 본문처럼 남은 표지 제목

# 절 제목은 짧고 마침표로 끝나지 않는다. 어미로는 못 거른다 — 이 회차의 절 제목
# 8개 중 5개가 "…했다"로 끝난다("1. 시작이 좋지 않았다 — 아침에 저장소가 깨져 있었다").
FLAT_HEADING_MAX = 80

# 이 워크어라운드를 적용할 회차를 **명시적으로 적는다**. 새 회차가 평탄화된 채로 들어오면
# 조용히 휴리스틱을 태우는 대신 멈춘다.
#
# 왜 자동으로 안 하는가 — 이 휴리스틱은 07-24 문서 하나를 실제로 열어보고 맞춘 것이다.
# "숫자.으로 시작하고 80자 이하면 절 제목", "문단 안 줄바꿈은 전부 정렬이 의미를 갖는
# 덩어리"는 그 문서에서 참인 것이지 일반 규칙이 아니다(그 문서에선 해당 문단 3개가
# 구성도·터미널 출력 전부였다 — 세어서 확인했다). 다른 문서에 그대로 먹이면 인용문이
# 코드블록이 되거나 본문 문장이 절 제목으로 승격되는데, **에러 없이** 그렇게 된다.
# 이 저장소가 반복해서 당한 게 정확히 그 '조용한 실패'다.
FLAT_ALLOWED = frozenset({"2026-07-24"})


def _is_flattened(doc) -> bool:
    return not any(
        (lv := _heading_level(p)) is not None and lv >= 1 for p in doc.paragraphs
    )


def _flat_heading_level(text: str) -> int | None:
    m = FLAT_HEADING.match(text)
    if not m or len(text) > FLAT_HEADING_MAX or text.rstrip().endswith("."):
        return None
    return 2 if m.group(2) else 1


def convert(path: Path) -> tuple[str, str, list[str]]:
    """docx → (제목, 마크다운 본문, 태그)."""
    doc = Document(str(path))
    date = path.stem.split("_")[-1]
    if date not in POSTS:
        raise SystemExit(f"{date}의 제목·태그가 POSTS에 없습니다. 스크립트에 추가하세요.")
    title, tags = POSTS[date]

    blocks: list[str] = []
    # 고정폭(터미널 출력) 줄을 모았다가 한 덩어리로 코드블록에 넣는다. 아래 _flush_mono 참고.
    mono_buf: list[str] = []
    seen_heading = False
    flat = _is_flattened(doc)
    if flat and date not in FLAT_ALLOWED:
        raise SystemExit(
            f"{date}: 이 문서에 Heading 스타일이 하나도 없습니다(평탄화). 그대로 변환하면\n"
            f"  절이 통째로 사라진 껍데기가 나오고, 되살리는 휴리스틱은 2026-07-24 문서\n"
            f"  하나에 맞춰 만든 것이라 다른 문서에는 조용히 잘못 먹을 수 있습니다.\n"
            f"  → 문서를 열어 확인한 뒤, 맞다면 FLAT_ALLOWED에 '{date}'를 추가하세요."
        )

    def _flush_mono() -> None:
        if mono_buf:
            blocks.append("```\n" + "\n".join(mono_buf) + "\n```")
            mono_buf.clear()

    for para in doc.paragraphs:
        text = para.text.rstrip()
        if not text.strip():
            continue

        # 터미널 출력(make_devlog의 ev())은 Consolas 문단으로 들어온다. 예전엔 이걸 못 알아봐서
        # **한 줄이 문단 하나씩** 흩어졌고, 표처럼 열을 맞춘 출력은 정렬이 통째로 사라졌다.
        # 이 회차들의 형식이 "터미널 출력을 그대로 싣는다"인데 발행본에서만 안 지켜지고 있었다.
        # (2026-07-28에 #21을 변환하다 발견. #20도 같은 상태였다)
        if _is_mono(para):
            mono_buf.append(text)
            continue
        _flush_mono()

        if flat and text == FLAT_TITLE:
            continue  # Title 스타일이 날아간 표지 제목

        level = _heading_level(para)
        if level == 0:
            continue  # 표지 제목은 버린다
        if level is None and flat:
            level = _flat_heading_level(text)

        if level is not None:
            seen_heading = True
            blocks.append(f"{'#' * (level + 1)} {text}")
            continue

        if flat and "\n" in text:
            # 문단 안의 줄바꿈(w:br)은 이 회차에선 전부 정렬이 의미를 갖는 덩어리다
            # (표지 구성도 1개 + 터미널 출력 2개). 그냥 두면 마크다운이 줄바꿈을 공백으로
            # 합쳐 한 줄로 뭉갠다. 스타일이 살아 있는 회차는 이 경로를 안 탄다.
            # 표지 영역에도 하나 있어서 _cover_line보다 먼저 본다.
            blocks.append(f"```\n{text}\n```")
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

        flat_bullet = bool(flat and FLAT_BULLET.match(text))
        # 스타일이 날아간 회차는 글머리표가 문단 첫 글자로 남아 있다("•  증명 3종: …").
        bullet_text = FLAT_BULLET.sub("", text) if flat_bullet else text
        if _is_bullet(para) or flat_bullet:
            # 연속된 불릿은 한 블록으로 묶어야 마크다운 목록이 끊기지 않는다
            if blocks and blocks[-1].startswith("- "):
                blocks[-1] += f"\n- {bullet_text}"
            else:
                blocks.append(f"- {bullet_text}")
            continue

        blocks.append(text)

    _flush_mono()  # 문서가 터미널 출력으로 끝나는 경우

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
