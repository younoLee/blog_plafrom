#!/usr/bin/env python3
"""공유 미리보기 카드(og:image) PNG를 만든다 — 1200x630.

왜 다시 만드나 (2026-08-12 실측): 라이브의 og-image.png가 **343x361**이었다.
`twitter:card=summary_large_image`와 카카오톡·슬랙의 큰 카드는 1200x630(1.91:1)을
기준으로 자르고 확대한다. 기준보다 작으면 확대돼 뭉개지거나 큰 카드 자체가 안 뜬다.

왜 라이브러리 없이 그리나 — 이 환경엔 PIL도 imagemagick도 없다(로컬 파이썬은 pip가
죽어 있다). 그리고 바이너리를 어디선가 받아 커밋하면 "이 그림이 어디서 왔는지"
아무도 답할 수 없게 된다. gen_pwa_icons.py가 같은 이유로 zlib만 쓰고 있으므로
그 PNG 작성기·번개 모양·브랜드 색을 그대로 빌려 쓴다(사본을 만들면 색이 갈라진다).

왜 글자를 도형으로 그리나 — 폰트 파일이 저장소에 없고(본문 폰트는 CDN에서 온다)
폰트 렌더러도 없다. 한글은 이 방식으로 그릴 수 없어서 **'DEV'만** 넣는다.
제목·설명은 어차피 카드에서 og:title/og:description으로 따로 보인다 —
이 그림이 할 일은 '어느 사이트인지'를 한눈에 주는 것까지다.

  scripts/gen_og_image.py       # frontend/public/og-image.png
"""
import pathlib
import struct
import sys
import zlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from gen_pwa_icons import BG, FG, BOLT, _chunk, _inside  # noqa: E402

W, H = 1200, 630
BG2 = (75, 31, 214)  # 왼쪽 위 #863bff → 오른쪽 아래로 어두워지는 대각 그라데이션

# 번개: 정사각 영역에 그린다(BOLT가 0~1 정규 좌표라서).
BOLT_X, BOLT_Y, BOLT_S = 150, 165, 300

# 워드마크 'DEV' — 획 두께 44, 높이 200. 좌표는 전부 캔버스 픽셀 기준이다.
TOP, BOT, STROKE = 215, 415, 44
MID = (TOP + BOT) / 2

D_X = 520  # D: 세로획 + 반달(바깥 타원 - 안쪽 타원)
D_RX, D_RY = 126, 100
E_X = 730  # E: 세로획 + 가로획 셋
E_W = 140
V_L, V_R = 910, 1080  # V: 아래에서 만나는 빗금 둘
V_MID_L, V_MID_R = V_L + 63, V_R - 63

V_LEFT = [(V_L, TOP), (V_L + STROKE, TOP), (V_MID_R, BOT), (V_MID_L, BOT)]
V_RIGHT = [(V_R - STROKE, TOP), (V_R, TOP), (V_MID_R, BOT), (V_MID_L, BOT)]


def _rect(x, y, x0, y0, x1, y1) -> bool:
    return x0 <= x < x1 and y0 <= y < y1


def _is_ink(x: float, y: float) -> bool:
    """이 픽셀이 흰색(전경)인가. 바운딩 박스로 먼저 걸러야 1200x630이 느려지지 않는다."""
    # 번개
    if BOLT_X <= x < BOLT_X + BOLT_S and BOLT_Y <= y < BOLT_Y + BOLT_S:
        if _inside((x - BOLT_X) / BOLT_S, (y - BOLT_Y) / BOLT_S, BOLT):
            return True
    if not (TOP <= y < BOT):
        return False

    # D
    if D_X <= x < D_X + 2 * D_RX:
        if _rect(x, y, D_X, TOP, D_X + STROKE, BOT):
            return True
        cx, cy = D_X + STROKE, MID
        dx, dy = (x - cx) / D_RX, (y - cy) / D_RY
        ix, iy = (x - cx) / (D_RX - STROKE), (y - cy) / (D_RY - STROKE)
        if x >= cx and dx * dx + dy * dy <= 1 and ix * ix + iy * iy > 1:
            return True
    # E
    if E_X <= x < E_X + E_W:
        if _rect(x, y, E_X, TOP, E_X + STROKE, BOT):
            return True
        if _rect(x, y, E_X, TOP, E_X + E_W, TOP + STROKE):
            return True
        if _rect(x, y, E_X, MID - STROKE / 2, E_X + E_W - 25, MID + STROKE / 2):
            return True
        if _rect(x, y, E_X, BOT - STROKE, E_X + E_W, BOT):
            return True
    # V
    if V_L <= x < V_R:
        if _inside(x, y, V_LEFT) or _inside(x, y, V_RIGHT):
            return True
    return False


def render() -> bytes:
    rows = bytearray()
    for y in range(H):
        rows.append(0)  # 스캔라인 필터 바이트(0 = None)
        ty = y / (H - 1)
        for x in range(W):
            if _is_ink(x + 0.5, y + 0.5):
                rows.extend(FG)
                continue
            # 대각 그라데이션. 알파는 안 쓴다(공유 카드는 항상 불투명하게 합성된다)
            t = (x / (W - 1) + ty) / 2
            rows.extend(round(a + (b - a) * t) for a, b in zip(BG, BG2))

    ihdr = struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0)  # 8bit RGB(알파 없음)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(bytes(rows), 9))
        + _chunk(b"IEND", b"")
    )


def main() -> None:
    out = pathlib.Path(__file__).resolve().parent.parent / "frontend" / "public" / "og-image.png"
    out.write_bytes(render())
    print(f"  {out.name}  {W}x{H}  {out.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
