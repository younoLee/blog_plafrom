#!/usr/bin/env python3
"""PWA 홈화면 아이콘(PNG)을 만든다.

왜 스크립트인가 — 이 환경엔 PIL도 imagemagick도 없고, 그렇다고 바이너리를
어디선가 받아 커밋하면 "이 그림이 어디서 왔는지" 아무도 답할 수 없게 된다.
파이썬 표준 라이브러리(zlib)만으로 PNG를 직접 써서, 아이콘을 **코드로** 남긴다.

왜 PNG여야 하나 — 매니페스트 자체는 SVG 아이콘을 받는다. 하지만 **iOS는
홈화면 아이콘으로 SVG를 안 쓴다**(apple-touch-icon은 PNG여야 한다). iOS에서
푸시를 받으려면 홈화면에 설치돼야 하므로, iOS를 포기하지 않는 한 PNG가 필요하다.

  scripts/gen_pwa_icons.py          # frontend/public/ 에 icon-192.png, icon-512.png

디자인은 favicon.svg와 같은 모양(막대 셋)이다. 제대로 된 아이콘이
생기면 이 파일을 지우고 그걸 넣으면 된다.
"""
import pathlib
import struct
import zlib

# 2026-08-18에 색과 모양을 갈았다. 전에는 보라(#863bff) 바탕에 번개였는데,
# 그 조합이 favicon.svg(흐린 타원 16개를 겹친 그라데이션 번개)에서 온 것이고
# 번개는 '자동으로 만들어진 표식'으로 읽힌다. 사이트 이름이 「블로그 만들기」로
# 정해지면서 색은 본문 강조색으로, 모양은 **글 목록**으로 바꿨다.
BG = (33, 91, 166)  # #215ba6 — index.css의 --color-accent
FG = (255, 255, 255)

# 길이가 줄어드는 가로 막대 셋 = 글 목록. 0~1 정규 좌표의 (x, y, w, h) 사각형이다.
# 번개 같은 다각형보다 이쪽이 작은 크기(16px 탭 아이콘)에서 안 뭉개진다.
BARS = [
    (0.22, 0.30, 0.56, 0.085),
    (0.22, 0.4575, 0.40, 0.085),
    (0.22, 0.615, 0.28, 0.085),
]


def _inside(px: float, py: float, bars: list[tuple[float, float, float, float]]) -> bool:
    """점이 막대 중 하나 안에 있는가. 사각형이라 좌표 비교면 끝난다
    (전에는 번개 다각형이라 광선 투사가 필요했다)."""
    return any(x <= px <= x + w and y <= py <= y + h for x, y, w, h in bars)


def _chunk(tag: bytes, data: bytes) -> bytes:
    """PNG 청크 = 길이 + 태그 + 데이터 + CRC32(태그+데이터)."""
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def render(size: int) -> bytes:
    """모서리를 둥글린 사각형 배경 위에 막대 셋. 알파는 모서리 바깥만 0."""
    radius = size * 0.22
    rows = bytearray()
    for y in range(size):
        rows.append(0)  # 각 스캔라인 앞의 필터 바이트(0 = None)
        for x in range(size):
            # 둥근 모서리: 코너 원의 중심에서의 거리로 판정
            cx = min(max(x + 0.5, radius), size - radius)
            cy = min(max(y + 0.5, radius), size - radius)
            dx, dy = x + 0.5 - cx, y + 0.5 - cy
            if dx * dx + dy * dy > radius * radius:
                rows.extend((0, 0, 0, 0))  # 모서리 바깥 = 투명
                continue
            color = FG if _inside(x / size, y / size, BARS) else BG
            rows.extend((*color, 255))

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)  # 8bit RGBA
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(bytes(rows), 9))
        + _chunk(b"IEND", b"")
    )


def main() -> None:
    out = pathlib.Path(__file__).resolve().parent.parent / "frontend" / "public"
    for size in (192, 512):
        path = out / f"icon-{size}.png"
        path.write_bytes(render(size))
        print(f"  {path.name}  {path.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
