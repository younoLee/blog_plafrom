#!/usr/bin/env python3
"""PWA 홈화면 아이콘(PNG)을 만든다.

왜 스크립트인가 — 이 환경엔 PIL도 imagemagick도 없고, 그렇다고 바이너리를
어디선가 받아 커밋하면 "이 그림이 어디서 왔는지" 아무도 답할 수 없게 된다.
파이썬 표준 라이브러리(zlib)만으로 PNG를 직접 써서, 아이콘을 **코드로** 남긴다.

왜 PNG여야 하나 — 매니페스트 자체는 SVG 아이콘을 받는다. 하지만 **iOS는
홈화면 아이콘으로 SVG를 안 쓴다**(apple-touch-icon은 PNG여야 한다). iOS에서
푸시를 받으려면 홈화면에 설치돼야 하므로, iOS를 포기하지 않는 한 PNG가 필요하다.

  scripts/gen_pwa_icons.py          # frontend/public/ 에 icon-192.png, icon-512.png

디자인은 favicon.svg의 색과 모양(번개)을 따라간 최소한이다. 제대로 된 아이콘이
생기면 이 파일을 지우고 그걸 넣으면 된다.
"""
import pathlib
import struct
import zlib

BG = (134, 59, 255)  # #863bff — favicon.svg의 브랜드 보라
FG = (255, 255, 255)

# 번개 모양을 0~1 정규 좌표의 다각형으로. favicon의 형태를 단순화한 것.
BOLT = [
    (0.56, 0.06), (0.22, 0.54), (0.44, 0.54),
    (0.38, 0.94), (0.76, 0.44), (0.53, 0.44),
]


def _inside(px: float, py: float, poly: list[tuple[float, float]]) -> bool:
    """광선 투사(ray casting) — 점에서 오른쪽으로 반직선을 쏴 변과 만난 횟수가
    홀수면 안쪽이다. 다각형 하나 채우자고 라이브러리를 들일 이유가 없다."""
    hit = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > py) != (y2 > py):
            xx = x1 + (py - y1) * (x2 - x1) / (y2 - y1)
            if px < xx:
                hit = not hit
    return hit


def _chunk(tag: bytes, data: bytes) -> bytes:
    """PNG 청크 = 길이 + 태그 + 데이터 + CRC32(태그+데이터)."""
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def render(size: int) -> bytes:
    """모서리를 둥글린 사각형 배경 위에 번개. 알파는 모서리 바깥만 0."""
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
            color = FG if _inside(x / size, y / size, BOLT) else BG
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
