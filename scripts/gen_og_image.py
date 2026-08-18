#!/usr/bin/env python3
"""공유 미리보기 카드(og:image) PNG를 만든다 — 1200x630.

왜 다시 만드나 (2026-08-12 실측): 라이브의 og-image.png가 **343x361**이었다.
`twitter:card=summary_large_image`와 카카오톡·슬랙의 큰 카드는 1200x630(1.91:1)을
기준으로 자르고 확대한다. 기준보다 작으면 확대돼 뭉개지거나 큰 카드 자체가 안 뜬다.

왜 라이브러리 없이 그리나 — 이 환경엔 PIL도 imagemagick도 없다(로컬 파이썬은 pip가
죽어 있다). 그리고 바이너리를 어디선가 받아 커밋하면 "이 그림이 어디서 왔는지"
아무도 답할 수 없게 된다. gen_pwa_icons.py가 같은 이유로 zlib만 쓰고 있으므로
그 PNG 작성기·모양·색을 그대로 빌려 쓴다(사본을 만들면 색이 갈라진다).

**2026-08-18에 그림을 갈았다.** 전에는 보라 그라데이션 위에 번개와 'DEV' 워드마크를
획 단위로 그렸다(letterform 60여 줄). 사이트 이름이 「블로그 만들기」가 되면서 그
워드마크는 틀린 글자가 됐고, 한글은 이 방식으로 그릴 수 없다 — 저장소에 폰트 파일도
렌더러도 없다. 그래서 **표식 하나만** 남긴다.

글자를 포기해도 되는 이유: 카드에는 og:title과 og:description이 **글자로 따로** 뜬다.
이 그림이 할 일은 거기까지 가기 전에 '어느 사이트인지'를 한눈에 주는 것이고, 그건
아이콘과 같은 표식이면 된다. 오히려 탭·홈화면·공유카드가 같은 모양이 되어 붙는다.

  scripts/gen_og_image.py       # frontend/public/og-image.png
"""
import pathlib
import struct
import sys
import zlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from gen_pwa_icons import BARS, BG, FG, _chunk, _inside  # noqa: E402

W, H = 1200, 630

# 표식을 놓을 정사각 영역(BARS가 0~1 정규 좌표라서).
#
# **잉크의 실제 경계로 가운데를 맞춘다.** BARS는 0~1 사각형 안에서 왼쪽 위에 치우쳐
# 있어서(x는 0.22~0.78, y는 0.30~0.70), 정사각형만 가운데 놓으면 그림이 왼쪽 위로
# 쏠려 보인다. 처음에 그렇게 뒀다가 화면에서 바로 티가 났다.
MARK_S = 420
_INK_X0, _INK_X1 = min(b[0] for b in BARS), max(b[0] + b[2] for b in BARS)
_INK_Y0, _INK_Y1 = min(b[1] for b in BARS), max(b[1] + b[3] for b in BARS)
MARK_X = round(W / 2 - MARK_S * (_INK_X0 + _INK_X1) / 2)
MARK_Y = round(H / 2 - MARK_S * (_INK_Y0 + _INK_Y1) / 2)

# 바탕은 단색이다. 전에는 대각 그라데이션이었는데, 화면에서 그라데이션을 걷어낸
# 것과 같은 이유로 여기서도 뺐다 — 공유 카드는 작게 뜨고, 거기서 그라데이션은
# 그냥 얼룩으로 보인다.


def render() -> bytes:
    rows = bytearray()
    for y in range(H):
        rows.append(0)  # 스캔라인 필터 바이트(0 = None)
        for x in range(W):
            px, py = x + 0.5, y + 0.5
            if (
                MARK_X <= px < MARK_X + MARK_S
                and MARK_Y <= py < MARK_Y + MARK_S
                and _inside((px - MARK_X) / MARK_S, (py - MARK_Y) / MARK_S, BARS)
            ):
                rows.extend(FG)
            else:
                rows.extend(BG)

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
