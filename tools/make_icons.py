"""Genera los iconos PNG del radar (estándar: zlib+struct, sin dependencias).

Radar: fondo azul oscuro, anillos cian, barrido ámbar, punto central.
Genera iconos para la PWA (192/512) y la extensión (16/48/128), además del SVG.
"""
from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

BG = (11, 18, 38)        # #0B1226
RING = (34, 211, 238)    # cian
RING_DIM = (34, 211, 238)
SWEEP = (245, 158, 11)   # ámbar
CENTER = (245, 158, 11)
GRID = (34, 211, 238)

ANGLES = (-50.0, 25.0)


def _render_px(S: int, half: float, x: float, y: float) -> tuple[int, int, int]:
    dx, dy = x - half, y - half
    d = math.hypot(dx, dy)
    maxr = half * 0.98
    ang = math.degrees(math.atan2(dy, dx))
    # fondo
    r, g, b = BG
    # anillos
    for f in (0.62, 0.42, 0.22):
        rr = half * f
        width = max(1.5, half * 0.012)
        if abs(d - rr) <= width:
            r, g, b = RING
    # retícula (líneas horizontales/verticales ténues)
    if abs(dy) < 1.2 and d < maxr:
        r, g, b = GRID
    if abs(dx) < 1.2 and d < maxr:
        r, g, b = GRID
    # barrido
    if ANGLES[0] <= ang <= ANGLES[1] and d <= maxr:
        t = (ang - ANGLES[0]) / (ANGLES[1] - ANGLES[0])
        fade = 0.35 + 0.65 * (1 - t) * (1 - d / maxr)
        r = int(r + (SWEEP[0] - r) * fade)
        g = int(g + (SWEEP[1] - g) * fade)
        b = int(b + (SWEEP[2] - b) * fade)
    # punto central
    if d <= half * 0.045:
        r, g, b = CENTER
    return (min(255, r), min(255, g), min(255, b))


def render(size: int) -> bytes:
    SS = 3
    S = size * SS
    half = S / 2
    big = bytearray()
    for y in range(S):
        row = bytearray()
        for x in range(S):
            row.extend(_render_px(S, half, x + 0.5, y + 0.5))
        # promediar bloques SS×SS -> 1 px de salida (downsample mientras renderiza)
        if big and len(big) >= size * 3 and (y % SS == 0):
            pass
        big.extend(row)
    # downsample por bloques
    out = bytearray()
    for by in range(size):
        for bx in range(size):
            acc = [0, 0, 0]
            for sy in range(SS):
                for sx in range(SS):
                    ix = (by * SS + sy) * S * 3 + (bx * SS + sx) * 3
                    acc[0] += big[ix]
                    acc[1] += big[ix + 1]
                    acc[2] += big[ix + 2]
            n = SS * SS
            out.extend((acc[0] // n, acc[1] // n, acc[2] // n))
    return _png(size, size, bytes(out))


def _png(w: int, h: int, rgb: bytes) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = bytearray()
    stride = w * 3
    for y in range(h):
        raw.append(0)  # filtro None
        raw.extend(rgb[y * stride:(y + 1) * stride])
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <rect width="512" height="512" rx="96" fill="#0B1226"/>
  <g fill="none" stroke="#22D3EE" stroke-width="6">
    <circle cx="256" cy="256" r="227"/>
    <circle cx="256" cy="256" r="154"/>
    <circle cx="256" cy="256" r="81"/>
    <line x1="26" y1="256" x2="486" y2="256"/>
    <line x1="256" y1="26" x2="256" y2="486"/>
  </g>
  <path d="M256 256 L 398 152 A 227 227 0 0 1 419 256 Z" fill="#F59E0B" opacity="0.55"/>
  <circle cx="256" cy="256" r="20" fill="#F59E0B"/>
</svg>
"""


def main() -> None:
    pwa_icons = ROOT / "pwa" / "icons"
    ext_icons = ROOT / "extension" / "icons"
    for d in (pwa_icons, ext_icons):
        d.mkdir(parents=True, exist_ok=True)

    for size in (512, 192):
        (pwa_icons / f"icon-{size}.png").write_bytes(render(size))
    (pwa_icons / "icon.svg").write_text(SVG, encoding="utf-8")
    for size in (16, 48, 128):
        (ext_icons / f"icon{size}.png").write_bytes(render(size))
    print("Iconos generados.")


if __name__ == "__main__":
    main()