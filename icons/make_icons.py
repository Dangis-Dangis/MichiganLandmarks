"""Generate the app icons (no third-party deps): a map pin with a classical
landmark/monument glyph - the standard "point of interest / historic site" motif.

Run: python icons/make_icons.py

Produces:
  App UI icons (this folder):
    icon-192.png, icon-512.png, icon-maskable-512.png
  Capacitor source images (../mobile/assets), for `npx @capacitor/assets generate`:
    icon-foreground.png, icon-background.png, icon-only.png
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "mobile" / "assets"

GREEN = (11, 61, 46)
WHITE = (255, 255, 255)
TRANSPARENT = (0, 0, 0, 0)

# pin geometry in normalized content space [0,1]
HEAD = (0.5, 0.40)
R_HEAD = 0.27
TIP_Y = 0.90
R_DISC = 0.175


def _rounded(u: float, v: float, r: float) -> bool:
    cx = min(max(u, r), 1 - r)
    cy = min(max(v, r), 1 - r)
    return ((u - cx) ** 2 + (v - cy) ** 2) <= r * r


def _in_pin(u: float, v: float) -> bool:
    if (u - HEAD[0]) ** 2 + (v - HEAD[1]) ** 2 <= R_HEAD ** 2:
        return True
    if HEAD[1] <= v <= TIP_Y:
        hw = R_HEAD * (TIP_Y - v) / (TIP_Y - HEAD[1])
        return abs(u - HEAD[0]) <= hw
    return False


def _in_disc(u: float, v: float) -> bool:
    return (u - HEAD[0]) ** 2 + (v - HEAD[1]) ** 2 <= R_DISC ** 2


def _in_glyph(u: float, v: float) -> bool:
    # pediment (triangular roof)
    if 0.315 <= v <= 0.360:
        t = (v - 0.315) / (0.360 - 0.315)
        if abs(u - 0.5) <= 0.11 * t:
            return True
    # architrave
    if 0.362 <= v <= 0.388 and abs(u - 0.5) <= 0.105:
        return True
    # columns
    if 0.392 <= v <= 0.476:
        for c in (0.428, 0.476, 0.524, 0.572):
            if abs(u - c) <= 0.013:
                return True
    # base
    if 0.480 <= v <= 0.506 and abs(u - 0.5) <= 0.115:
        return True
    return False


def _pixel(u: float, v: float, scale: float, rounded: bool, solid_bg: bool):
    if rounded and not _rounded(u, v, 0.1875):
        return TRANSPARENT
    base = (GREEN[0], GREEN[1], GREEN[2], 255) if solid_bg else TRANSPARENT
    cu = (u - 0.5) / scale + 0.5
    cv = (v - 0.5) / scale + 0.5

    px = base
    if _in_pin(cu, cv):
        px = (WHITE[0], WHITE[1], WHITE[2], 255)
    if _in_disc(cu, cv):
        # On the transparent-foreground layer the disc lets the green background
        # show through; on a solid icon it is just green.
        px = (GREEN[0], GREEN[1], GREEN[2], 255) if solid_bg else TRANSPARENT
    if _in_glyph(cu, cv):
        px = (WHITE[0], WHITE[1], WHITE[2], 255)
    return px


def render(size: int, *, scale: float, rounded: bool, solid_bg: bool) -> bytes:
    raw = bytearray()
    for y in range(size):
        raw.append(0)
        v = (y + 0.5) / size
        for x in range(size):
            u = (x + 0.5) / size
            r, g, b, a = _pixel(u, v, scale, rounded, solid_bg)
            raw.extend((r, g, b, a))
    return _png(size, size, bytes(raw))


def solid(size: int, rgb) -> bytes:
    row = bytes((0,)) + bytes(rgb + (255,)) * size
    return _png(size, size, row * size)


def _png(w: int, h: int, raw: bytes) -> bytes:
    def chunk(typ: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + typ + data +
                struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF))
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def main() -> None:
    # App UI icons
    (HERE / "icon-192.png").write_bytes(render(192, scale=0.86, rounded=True, solid_bg=True))
    (HERE / "icon-512.png").write_bytes(render(512, scale=0.86, rounded=True, solid_bg=True))
    (HERE / "icon-maskable-512.png").write_bytes(render(512, scale=0.62, rounded=False, solid_bg=True))

    # Capacitor source images (1024) for @capacitor/assets
    ASSETS.mkdir(parents=True, exist_ok=True)
    (ASSETS / "icon-background.png").write_bytes(solid(1024, GREEN))
    (ASSETS / "icon-foreground.png").write_bytes(render(1024, scale=0.62, rounded=False, solid_bg=False))
    (ASSETS / "icon-only.png").write_bytes(render(1024, scale=0.72, rounded=False, solid_bg=True))

    print("wrote web icons (icons/) and Capacitor sources (mobile/assets/)")


if __name__ == "__main__":
    main()
