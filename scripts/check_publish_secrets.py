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

## 왜 자가검증(--selftest)이 있나

이 검사는 blocked 목록이 비면 그냥 0을 낸다. 즉 **탐지기가 통째로 죽어도 초록**이고,
초록은 "발행물에 실제 값 0건"이라는 사실 주장으로 나간다 — 이 저장소가 이름 붙인
'검사인 척하는 검사'다. 같은 CI에 있는 글투 검사가 08-27에 정확히 그 상태였다
(삼항 반복 탐지기가 역참조 정규식이라 아무것도 못 잡는데, 오탐 3건 때문에 죽은 줄
몰랐다). 그래서 여기도 같은 장치를 둔다: **일부러 넣은 가짜 값을 반드시 잡는가**를
먼저 확인하고, 못 잡으면 0이 아닌 종료코드를 낸다. (2026-09-02)

⚠️ 아래 고정값은 **명백히 가짜여야 한다.** 진짜처럼 생긴 값을 넣으면 gitleaks 잡이
이 파일 자체를 잡아 CI가 다른 이유로 빨개진다. IP는 RFC 2544 벤치마크 대역, DNS는
RFC 5737 문서용 주소를 쓰고, AKIA 키는 **문자열을 이어붙여** 만든다
(.gitleaks.toml의 aws-access-key-id-strict 규칙이 `AKIA[0-9A-Z]{16}` 연속 리터럴을
잡으므로, 소스에 그 모양이 통째로 있으면 안 된다).

사용법:  python3 scripts/check_publish_secrets.py [경로...]
         (인자가 없으면 content/devlog/*.md 와 scripts/make_devlog*.py 를 본다)
         python3 scripts/check_publish_secrets.py --selftest
"""

from __future__ import annotations

import glob
import os
import re
import sys
import tempfile

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

# 버전 문자열(1.2.3.4)이 IP로 잡히는 걸 줄인다. 앞 글자가 더 긴 토큰의 일부일 때만 넘긴다.
#
# ⚠️ **2026-09-04까지 이 문자 집합에 `= / @ :` 가 들어 있었다.** 그래서 `ssh user@1.2.3.4`,
# `http://1.2.3.4`, `PUBLIC_IP=1.2.3.4`, `host=1.2.3.4` 네 형태가 전부 검사를 통과했다.
# 개발일지는 터미널 출력을 그대로 싣는 형식이라 **주소가 새는 모양이 정확히 그 넷**이고,
# 즉 이 검사는 가장 흔한 누출만 골라서 놓치고 있었다. 실측(09-04): 같은 주소를 여섯 가지
# 형태로 넣었더니 공백 앞 두 개만 잡혔다.
#
# 자가검증도 그 구멍을 못 봤다. IP 픽스처가 `"접속 주소는 … 이었다"` 공백 앞 하나뿐이라
# 반쪽만 살아 있는 탐지기를 초록으로 통과시켰다. 그래서 아래 SELFTEST_HITS 에 네 형태를
# 전부 넣었다 — 다시 좁혀지면 거기서 먼저 빨개진다.
#
# 지금 규칙: 앞 글자가 영숫자나 `.` 이면(= 더 긴 토큰의 일부) 넘기고, `==` 로 끝나면
# 버전 핀으로 보고 넘긴다. `= / @ :` 뒤는 **오히려 IP 라는 신호**라 넘기지 않는다.
_VERSIONISH = re.compile(r"[A-Za-z0-9.]$")
_VERSION_PIN = "=="  # pip 스타일 버전 핀(`pretendard==1.2.3.4`)


def _looks_like_version(line: str, start: int) -> bool:
    """IP 로 잡힌 자리가 실은 버전 문자열의 일부인가."""
    before = line[:start]
    if _VERSIONISH.search(before):
        return True
    return before.endswith(_VERSION_PIN)

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
            # `python3.12.4.1` 이나 `pretendard==1.2.3.4` 같은 버전 문자열을 거른다.
            # 앞 글자 한 개가 아니라 **앞부분 전체**를 넘긴다 — `==` 를 보려면 두 글자가 필요하다.
            if m.start() and _looks_like_version(line, m.start()):
                continue
            blocked.append(f"{path}:{n}  공인 IP  {_hide(v)}")
        for label, pat in WARN:
            for m in pat.finditer(line):
                warned.append(f"{path}:{n}  {label}  {_hide(m.group(0))}")
    return blocked, warned


# ── 자가검증 고정값 ──────────────────────────────────────────────────────────
# 전부 **명백히 가짜**다(머리말의 ⚠️ 참고). 진짜처럼 생긴 값을 넣으면 gitleaks가
# 이 파일을 잡는다 — 검사를 지키려다 다른 검사를 깨는 셈이 된다.
#
# AKIA 키는 소스에 연속 리터럴로 두지 않는다. .gitleaks.toml 의
# aws-access-key-id-strict 가 `\b(?:AKIA|…)[0-9A-Z]{16}\b` 를 잡으므로,
# 이어붙여 만들면 파일 내용에는 그 모양이 존재하지 않는다.
_FAKE_AKIA = "AKIA" + "SELFTESTFAKE0000"  # 실재하지 않는 자리표시자
_FAKE_AKIA_OK = "AKIA" + "IOSFODNN7EXAMPLE"  # AWS 공식 문서의 예시 키(ALLOW 대상)

# (기대 라벨, 그 라벨이 반드시 나와야 하는 한 줄)
SELFTEST_HITS: list[tuple[str, str]] = [
    # 예약 도메인이 아니고 더미 표식도 없는 주소 → 막아야 한다.
    ("이메일 주소", "가입 확인: fake-selftest@not-a-real-domain.kr"),
    # 198.18.0.0/15 는 RFC 2544 벤치마크 전용이라 실제 호스트가 아니지만,
    # 사설·문서용 예외 목록에는 없으므로 이 검사는 '공인 IP'로 잡아야 한다.
    ("공인 IP", "접속 주소는 198.18.0.1 이었다"),
    # ⚠️ 아래 넷은 **2026-09-04까지 전부 통과하던 형태**다(_VERSIONISH 주석 참고).
    # 공백 앞 형태 하나만 시험하고 있어서 반쪽짜리 탐지기가 초록으로 지나갔다.
    # 개발일지가 터미널 출력을 그대로 싣는 형식이라 실제로 새는 모양이 이 넷이므로,
    # 잡아야 할 것의 대표는 위 한 줄이 아니라 여기까지다.
    ("공인 IP", "ssh -i key.pem ec2-user@198.18.0.1"),
    ("공인 IP", "curl http://198.18.0.1:8000/api/status"),
    ("공인 IP", "PUBLIC_IP=198.18.0.1"),
    ("공인 IP", "오리진 host=198.18.0.1 로 바꿨다"),
    ("AWS 액세스 키", f"export AWS_ACCESS_KEY_ID={_FAKE_AKIA}"),
    # 호스트명의 숫자는 RFC 5737 문서용 대역이다(203.0.113.0/24).
    ("EC2 퍼블릭 DNS", "ssh ec2-user@ec2-203-0-113-9.ap-northeast-2.compute.amazonaws.com"),
]

# 경고(종료코드에는 안 들어가지만 죽으면 역시 조용하다) 쪽도 같이 본다.
SELFTEST_WARNS: list[tuple[str, str]] = [
    ("인스턴스 ID", "대상 i-0123456789abcdef0 을 껐다"),
    ("볼륨 ID", "루트 볼륨 vol-0123456789abcdef0 을 붙였다"),
]

# 하나라도 걸리면 안 되는 줄. 여기가 깨지면 검사가 '영구 빨간불'이 되고,
# 영구 빨간불은 결국 꺼진다 — 이 저장소가 여러 번 적어둔 실패 방식이다.
SELFTEST_MISSES: list[str] = [
    "문의는 hong@example.com 으로 주세요",  # RFC 2606 예약 도메인
    "이미 가린 자리: ...@gmail.com",  # 사람이 손으로 마스킹한 것
    "사설망 192.168.0.1 과 루프백 127.0.0.1",
    "문서용 예약 대역 203.0.113.9 · 198.51.100.7 · 192.0.2.4",
    "공개 리졸버 1.1.1.1",
    "pip 목록: pretendard==1.2.3.4",  # 버전 핀이 IP로 잡히면 안 된다
    "빌드 v1.2.3.4 로 올렸다",  # 앞 글자가 영숫자면 더 긴 토큰의 일부다
    "경로 python3.12.4.1 확인",  # 위와 같은 이유
    f"AWS 문서의 예시 키 {_FAKE_AKIA_OK}",
]


def selftest() -> int:
    """일부러 넣은 가짜 값을 실제로 잡는지 확인한다. 못 잡으면 0이 아닌 코드.

    정규식을 직접 부르지 않고 **scan() 을 통째로 태운다.** 탐지기가 살아 있어도
    scan() 의 조립부(ALLOW 대조·_hide·라벨 전달)가 깨지면 결과는 똑같이 '0건'이라,
    거기까지 포함해서 재야 의미가 있다.
    """
    fail = 0

    # 목록 자체가 비면 아래 for 문이 한 번도 안 돌아 **조용히 통과**한다.
    # 이 파일이 막으려는 실패 방식이 바로 그것이라 개수를 먼저 못 박는다.
    if not BLOCK:
        print("❌ BLOCK 목록이 비었다 — 막는 검사가 하나도 없다", file=sys.stderr)
        fail += 1
    if not WARN:
        print("❌ WARN 목록이 비었다 — 알리는 검사가 하나도 없다", file=sys.stderr)
        fail += 1

    def run(lines: list[str]) -> tuple[list[str], list[str]]:
        fd, path = tempfile.mkstemp(suffix=".selftest.md", text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")
            return scan(path)
        finally:
            os.unlink(path)

    for label, line in SELFTEST_HITS:
        blocked, _ = run([line])
        if not any(f"  {label}  " in b for b in blocked):
            print(f"❌ 잡아야 하는데 놓쳤다 [{label}]: {line}", file=sys.stderr)
            fail += 1

    for label, line in SELFTEST_WARNS:
        _, warned = run([line])
        if not any(f"  {label}  " in w for w in warned):
            print(f"❌ 경고해야 하는데 놓쳤다 [{label}]: {line}", file=sys.stderr)
            fail += 1

    blocked, warned = run(SELFTEST_MISSES)
    for b in blocked:
        print(f"❌ 잡으면 안 되는데 잡았다: {b}", file=sys.stderr)
        fail += 1
    for w in warned:
        print(f"❌ 경고하면 안 되는데 경고했다: {w}", file=sys.stderr)
        fail += 1

    # 찾은 값을 그대로 찍지 않는다는 약속도 검사 대상이다. 이게 깨지면 CI 로그가
    # 곧 유출 경로가 된다(이 검사의 출력은 공개 로그에 남는다).
    blocked, _ = run([f"export AWS_ACCESS_KEY_ID={_FAKE_AKIA}"])
    if any(_FAKE_AKIA in b for b in blocked):
        print("❌ _hide()가 값을 안 가린다 — CI 로그에 원문이 남는다", file=sys.stderr)
        fail += 1

    if fail:
        print(f"자가검증 실패 {fail}건 — 탐지기가 죽었다. 초록을 믿지 마라.")
        return 1
    print(
        f"자가검증 통과 — 막는 {len(SELFTEST_HITS)}종 · 알리는 {len(SELFTEST_WARNS)}종을 "
        f"실제로 잡고, 정상값 {len(SELFTEST_MISSES)}줄은 통과시킨다"
    )
    return 0


def main(argv: list[str]) -> int:
    if argv[1:2] == ["--selftest"]:
        return selftest()

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
