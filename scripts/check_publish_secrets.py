#!/usr/bin/env python3
"""발행되는 글에 운영 실제 값이 실렸는지 본다.

## 왜 필요한가

개발일지는 **터미널 출력을 그대로 싣는** 형식이다. 그게 이 글의 값어치인데, 동시에
`psql`로 users 테이블을 조회한 화면이나 `curl checkip`의 응답이 같이 실린다는 뜻이다.
2026-08-19 보안검사가 실제로 잡았다 — 발행된 34편 중 5편에 실계정 이메일 3개(역할까지)와
집 공인 IP 2개, 오리진 EC2 호스트명이 라이브로 나가 있었다. RSS와 검색 인덱스에도 들어가
사이트 검색창으로 찾아졌다.

**사람 눈으로는 계속 샌다.** 쓸 때는 그게 화면 캡처의 일부로 보이고, 고칠 때는 이미
발행된 뒤다. 그래서 기계가 본다.

## 무엇을 어떻게 보나

- **막는다(exit 1)**: 이메일 주소, 공인 IP, AWS 액세스 키, EC2 퍼블릭 DNS.
  이 넷은 '사람과 접점'이라 새면 되돌릴 수 없다(검색엔진·RSS 리더가 이미 가져간다).
- **알린다(경고, exit 0)**: 인스턴스·볼륨 ID. 자격증명이 아니고 운영 문서에도 쓰이므로
  막지 않는다. 다만 새 편에 처음 등장하면 눈으로 한 번 보라는 뜻이다.

예약 대역·예약 도메인은 통과시킨다(RFC 5737의 203.0.113.0/24 등, RFC 2606의 example.com).
**마스킹할 때 그 값들을 쓰라는 뜻**이기도 하다 — 아무 숫자나 넣으면 남의 실주소가 된다.

## 왜 허용 목록을 파일 상단에 두나

'이건 남겨도 되는 값'이 반드시 생긴다(공개 서비스 주소, 문서용 예시). 그때 검사를 통째로
끄면 다음 편부터 아무도 안 본다. 예외는 여기 한 줄로 적고, 적는 순간 근거가 남는다.

사용법:  python3 scripts/check_publish_secrets.py [경로...]
         (인자가 없으면 content/devlog/*.md 와 scripts/make_devlog*.py 를 본다)
"""

from __future__ import annotations

import glob
import re
import sys

# ── 남겨도 되는 값 ────────────────────────────────────────────────────────────
# 여기 적는 값은 '공개해도 되는 이유'가 있는 것이다. 늘릴 때 이유를 한 줄 같이 적을 것.
ALLOW = {
    "d2j66m9udyg9yq.cloudfront.net",  # 이 블로그의 공개 주소
    "d2.naver.com",  # 글투 비교 대상으로 인용한 공개 블로그
}

# 이메일: 예약 도메인(example.*)과 명백한 더미는 통과.
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_EMAIL_OK = re.compile(
    # 예약 도메인(RFC 2606) · 예약 TLD(RFC 6761: .test .example .invalid .localhost) ·
    # 명백한 더미 · 그리고 **로컬파트가 이미 자리표시인 것**(`...@gmail.com`처럼 사람이
    # 손으로 가려 쓴 것). 마지막 것을 안 빼면 이미 마스킹한 자리가 계속 걸린다.
    r"@(example\.(com|org|net)|x\.com|b\.com)"
    r"|\.(test|example|invalid|local|localhost)$"
    r"|@test\.com"
    r"|noreply|users\.noreply"
    r"|^[.\u2026*]+@",
    re.I,
)

# IP: 사설·루프백·링크로컬·문서용 예약 대역은 통과.
_IP = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_IP_OK = re.compile(
    r"^("
    r"10\.|127\.|0\.|169\.254\.|192\.168\.|255\.|224\.|"
    r"172\.(1[6-9]|2\d|3[01])\.|"
    r"203\.0\.113\.|198\.51\.100\.|192\.0\.2\.|"  # RFC 5737 문서용
    r"1\.1\.1\.1$|8\.8\.8\.8$"  # 널리 알려진 공개 리졸버
    r")"
)

# 버전 문자열(1.2.3.4)이 IP로 잡히는 걸 줄인다 — 앞뒤에 글자가 붙어 있으면 넘긴다.
_VERSIONISH = re.compile(r"[A-Za-z=/@:._-]$")

BLOCK = [
    ("이메일 주소", _EMAIL, _EMAIL_OK),
    ("AWS 액세스 키", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), re.compile(r"AKIAIOSFODNN7")),
    (
        "EC2 퍼블릭 DNS",
        re.compile(r"\bec2-(?:\d{1,3}-){3}\d{1,3}\.[a-z0-9-]+\.compute\.amazonaws\.com\b"),
        re.compile(r"(?!)"),  # 예외 없음
    ),
]

WARN = [
    ("인스턴스 ID", re.compile(r"\bi-[0-9a-f]{8,17}\b")),
    ("볼륨 ID", re.compile(r"\bvol-[0-9a-f]{8,17}\b")),
]


def _hide(v: str) -> str:
    """찾은 값을 그대로 안 찍는다. 이 검사의 출력이 CI 로그에 남기 때문이다."""
    return v[:3] + "…" + v[-4:] if len(v) > 8 else v[:2] + "…"


def scan(path: str) -> tuple[list[str], list[str]]:
    blocked: list[str] = []
    warned: list[str] = []
    for n, line in enumerate(open(path, encoding="utf-8"), 1):
        for label, pat, ok in BLOCK:
            for m in pat.finditer(line):
                v = m.group(0)
                if v in ALLOW or ok.search(v):
                    continue
                blocked.append(f"{path}:{n}  {label}  {_hide(v)}")
        for m in _IP.finditer(line):
            v = m.group(0)
            if v in ALLOW or _IP_OK.match(v):
                continue
            # `python3.12.4.1` 같은 것과 `Pretendard 1.2.3.4` 같은 것을 거른다
            if m.start() and _VERSIONISH.search(line[m.start() - 1]):
                continue
            blocked.append(f"{path}:{n}  공인 IP  {_hide(v)}")
        for label, pat in WARN:
            for m in pat.finditer(line):
                warned.append(f"{path}:{n}  {label}  {_hide(m.group(0))}")
    return blocked, warned


def main(argv: list[str]) -> int:
    targets = argv[1:] or sorted(
        set(glob.glob("content/devlog/*.md") + glob.glob("scripts/make_devlog*.py"))
    )
    if not targets:
        print("볼 파일이 없다", file=sys.stderr)
        return 1

    blocked: list[str] = []
    warned: list[str] = []
    for t in targets:
        b, w = scan(t)
        blocked += b
        warned += w

    if warned:
        print(f"경고 {len(warned)}건 — 자격증명은 아니지만 새 편이면 한 번 볼 것")
        for w in warned:
            print(f"  {w}")

    if blocked:
        print(f"\n실제 값이 발행물에 있다 — {len(blocked)}건")
        for b in blocked:
            print(f"  {b}")
        print(
            "\n마스킹하고 다시 돌려라. 문서용 예약값을 쓸 것: "
            "이메일은 example.com, IP는 203.0.113.x(RFC 5737).\n"
            "**scripts/make_devlog_*.py 의 원본도 같이 고쳐야 한다** — 안 고치면 "
            "재생성할 때 되살아난다.\n"
            "남겨도 되는 값이면 이 파일 상단 ALLOW에 이유와 함께 적어라."
        )
        return 1

    print(f"발행물 {len(targets)}개 — 실제 값 0건")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
