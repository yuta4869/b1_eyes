#!/usr/bin/env python3
"""Generate the VLM Camera app icon as PNG (1024x1024). Run once."""
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(__file__).parent / "build" / "icon_src.png"
OUT.parent.mkdir(exist_ok=True)

S = 1024


def radial_gradient(size, inner, outer):
    img = Image.new("RGB", (size, size), outer)
    px = img.load()
    cx = cy = size / 2
    maxr = size / 2 * math.sqrt(2)
    for y in range(size):
        for x in range(size):
            r = math.hypot(x - cx, y - cy) / maxr
            r = min(1.0, r)
            px[x, y] = tuple(int(inner[i] + (outer[i] - inner[i]) * r) for i in range(3))
    return img


def rounded_mask(size, radius):
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    return m


def main():
    bg = radial_gradient(S, (90, 140, 240), (25, 40, 90))
    icon = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    icon.paste(bg, (0, 0), rounded_mask(S, int(S * 0.22)))

    draw = ImageDraw.Draw(icon, "RGBA")

    cx, cy = S // 2, int(S * 0.52)
    r_outer = int(S * 0.32)
    r_mid = int(S * 0.26)
    r_inner = int(S * 0.18)
    r_pupil = int(S * 0.11)

    draw.ellipse((cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer),
                 fill=(15, 25, 60, 255))
    draw.ellipse((cx - r_mid, cy - r_mid, cx + r_mid, cy + r_mid),
                 fill=(35, 55, 110, 255))
    draw.ellipse((cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner),
                 fill=(10, 15, 35, 255))
    draw.ellipse((cx - r_pupil, cy - r_pupil, cx + r_pupil, cy + r_pupil),
                 fill=(180, 220, 255, 255))

    hl = int(S * 0.04)
    draw.ellipse((cx - r_pupil + hl, cy - r_pupil + hl,
                  cx - r_pupil + hl * 3, cy - r_pupil + hl * 3),
                 fill=(255, 255, 255, 230))

    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    rg = int(S * 0.38)
    gdraw.ellipse((cx - rg, cy - rg, cx + rg, cy + rg), fill=(80, 200, 255, 70))
    glow = glow.filter(ImageFilter.GaussianBlur(40))
    icon = Image.alpha_composite(icon, glow)

    bracket = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bracket)
    L = int(S * 0.06)
    W = int(S * 0.018)
    top = int(S * 0.16)
    bottom = int(S * 0.86)
    left = int(S * 0.16)
    right = int(S * 0.86)
    color = (255, 255, 255, 230)

    def rect(x0, y0, x1, y1):
        bd.rectangle((min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)), fill=color)

    for (x, y, dx, dy) in [
        (left, top, +1, +1), (right, top, -1, +1),
        (left, bottom, +1, -1), (right, bottom, -1, -1),
    ]:
        rect(x, y, x + dx * L, y + dy * W)
        rect(x, y, x + dx * W, y + dy * L)
    icon = Image.alpha_composite(icon, bracket)

    text_layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    td = ImageDraw.Draw(text_layer)
    font = None
    for cand in [
        "/System/Library/Fonts/SFNS.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/HelveticaNeue.ttc",
    ]:
        try:
            font = ImageFont.truetype(cand, size=int(S * 0.13))
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default()
    label = "VLM"
    bbox = td.textbbox((0, 0), label, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    td.text(((S - tw) // 2, int(S * 0.06)), label, font=font, fill=(255, 255, 255, 240))
    icon = Image.alpha_composite(icon, text_layer)

    final = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    final.paste(icon, (0, 0), rounded_mask(S, int(S * 0.22)))
    final.save(OUT)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
