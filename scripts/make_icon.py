"""Render the Tracey app icon into src/tracey/resources.

    uv run python scripts/make_icon.py

Writes `icon.png` (1024 px), `logo.png` (in-app logo), `tracey.ico` (Windows, 16–256 px) and
`tracey.icns` (macOS, padded to Apple's icon grid with a drop shadow).
Small sizes are rendered with less detail so they stay readable.
"""

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parents[1] / "src" / "tracey" / "resources"
SS = 4  # supersampling, Pillow does not anti-alias shapes

BG_TOP, BG_BOTTOM = (31, 35, 52), (12, 14, 22)
FILL_A, FILL_B = (99, 102, 241), (34, 211, 238)  # indigo → cyan
WHITE = (255, 255, 255)

# the traced shape: anchors of a smooth closed path, in a 1000 unit box
ANCHORS = [(200, 615), (370, 240), (585, 375), (805, 315), (680, 790)]
HANDLE_ANCHOR = 1  # anchor whose bezier handles are drawn


def squircle(size: float, n: float = 5, steps: int = 720) -> list[tuple[float, float]]:
    r = size / 2
    t = np.linspace(0, 2 * np.pi, steps, endpoint=False)
    c, s = np.cos(t), np.sin(t)
    x = np.sign(c) * np.abs(c) ** (2 / n)
    y = np.sign(s) * np.abs(s) ** (2 / n)
    return list(zip(r + r * x, r + r * y))


def gradient(size: int, a, b, angle_deg: float) -> Image.Image:
    angle = np.radians(angle_deg)
    yy, xx = np.mgrid[0:size, 0:size] / max(size - 1, 1)
    t = (xx - 0.5) * np.cos(angle) + (yy - 0.5) * np.sin(angle)
    t = (t - t.min()) / (t.max() - t.min())
    rgb = np.array(a) * (1 - t[..., None]) + np.array(b) * t[..., None]
    return Image.fromarray(rgb.astype(np.uint8), "RGB").convert("RGBA")


def tangents(points: list[tuple[float, float]], tension: float = 0.36):
    """Catmull-Rom style tangents, scaled to bezier handle offsets."""
    n = len(points)
    out = []
    for i in range(n):
        (px, py), (nx, ny) = points[i - 1], points[(i + 1) % n]
        out.append(((nx - px) * tension, (ny - py) * tension))
    return out


def bezier_loop(points, handles, steps: int = 64) -> list[tuple[float, float]]:
    pts = []
    n = len(points)
    for i in range(n):
        p0, p3 = np.array(points[i]), np.array(points[(i + 1) % n])
        p1 = p0 + handles[i]
        p2 = p3 - handles[(i + 1) % n]
        for t in np.linspace(0, 1, steps, endpoint=False):
            u = 1 - t
            pts.append(tuple(u**3 * p0 + 3 * u * u * t * p1 + 3 * u * t * t * p2 + t**3 * p3))
    return pts


def artwork(size: int, detailed: bool, weight: float = 1) -> Image.Image:
    """The squircle tile with the traced shape, filling a `size` canvas.

    `weight` thickens the outline, handles and anchors for small display sizes.
    """
    big = size * SS
    k = big / 1000  # artwork units → pixels

    tile_mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(tile_mask).polygon(squircle(big), fill=255)
    tile = gradient(big, BG_TOP, BG_BOTTOM, 90)
    # soft indigo glow behind the shape
    glow = Image.new("L", (big, big), 0)
    ImageDraw.Draw(glow).ellipse([big * 0.18, big * 0.12, big * 0.9, big * 0.84], fill=110)
    glow = glow.filter(ImageFilter.GaussianBlur(big * 0.12))
    tile = Image.composite(Image.new("RGBA", (big, big), FILL_A + (255,)), tile, glow)

    anchors = [(x * k, y * k) for x, y in ANCHORS]
    handles = tangents(anchors)
    outline = bezier_loop(anchors, [np.array(h) for h in handles])

    shape_mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(shape_mask).polygon(outline, fill=255)
    fill = gradient(big, FILL_A, FILL_B, 35)
    tile = Image.composite(fill, tile, shape_mask.point(lambda v: v * 0.92))

    draw = ImageDraw.Draw(tile)
    stroke = (12 * weight if detailed else 26) * k
    draw.line(outline + outline[:1], fill=WHITE, width=round(stroke), joint="curve")

    if detailed:
        ax, ay = anchors[HANDLE_ANCHOR]
        hx, hy = handles[HANDLE_ANCHOR]
        ends = [(ax - hx * 1.05, ay - hy * 1.05), (ax + hx * 1.05, ay + hy * 1.05)]
        for ex, ey in ends:
            draw.line([(ax, ay), (ex, ey)], fill=WHITE, width=round(6 * weight * k))
        for ex, ey in ends:
            r = 19 * weight * k
            draw.ellipse([ex - r, ey - r, ex + r, ey + r], fill=WHITE)
        for i, (x, y) in enumerate(anchors):
            r = (34 if i == HANDLE_ANCHOR else 26) * weight * k
            draw.rectangle([x - r, y - r, x + r, y + r], fill=WHITE)
            inner = r - 9 * weight * k
            color = FILL_A if i == HANDLE_ANCHOR else BG_BOTTOM
            draw.rectangle([x - inner, y - inner, x + inner, y + inner], fill=color + (255,))

    # hairline highlight along the tile edge
    edge = Image.new("L", (big, big), 0)
    ImageDraw.Draw(edge).line(squircle(big - 2 * SS) + squircle(big - 2 * SS)[:1], fill=40, width=2 * SS)
    tile = Image.composite(Image.new("RGBA", (big, big), WHITE + (255,)), tile, edge)

    tile.putalpha(tile_mask)
    return tile.resize((size, size), Image.Resampling.LANCZOS)


def windows_icon(size: int) -> Image.Image:
    """Tile filling the canvas with a hair of margin, like Windows 11 icons."""
    margin = max(1, round(size * 0.03))
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    tile = artwork(size - 2 * margin, detailed=size >= 64)
    canvas.alpha_composite(tile, (margin, margin))
    return canvas


def macos_icon(size: int) -> Image.Image:
    """Apple's grid: an 824/1024 tile, centred, with a soft drop shadow."""
    body = round(size * 824 / 1024)
    offset = (size - body) // 2
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    shadow = Image.new("L", (size, size), 0)
    shifted = [(x + offset, y + offset + size * 0.012) for x, y in squircle(body)]
    ImageDraw.Draw(shadow).polygon(shifted, fill=round(255 * 0.45))
    shadow = shadow.filter(ImageFilter.GaussianBlur(size * 0.014))
    canvas.putalpha(shadow)  # black, shaped by the blurred tile

    canvas.alpha_composite(artwork(body, detailed=size >= 64), (offset, offset))
    return canvas


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    windows_icon(1024).save(OUT / "icon.png")
    # in-app logo, shown at ~32 px: keeps the anchors, drawn heavier to stay visible
    artwork(192, detailed=True, weight=2.2).save(OUT / "logo.png")

    ico_sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    frames = [windows_icon(s) for s in ico_sizes]
    frames[-1].save(OUT / "tracey.ico", sizes=[(s, s) for s in ico_sizes], append_images=frames[:-1])

    icns_frames = [macos_icon(s) for s in (32, 64, 128, 256, 512, 1024)]
    icns_frames[-1].save(OUT / "tracey.icns", append_images=icns_frames[:-1])
    icns_frames[-1].save(OUT / "icon-macos.png")
    print(f"icons written to {OUT}")


if __name__ == "__main__":
    main()
