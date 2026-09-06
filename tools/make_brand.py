"""Render the CardPerks brand images.

Draws the icon with Pillow at high resolution and downsamples, so there is no SVG
toolchain to install. Output goes to brands/cardperks/, laid out the way the
home-assistant/brands repo wants a custom integration: icon.png (256x256),
icon@2x.png (512x512), logo.png (256x128) and logo@2x.png (512x256), all
transparent PNG. Re-run after changing anything here.

    .venv-win/Scripts/python.exe tools/make_brand.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "brands" / "cardperks"

# Card body, stripe, chip and the check badge. Colour is identity here, not meaning,
# so nothing on the dashboard's captured/forfeited scheme is reused.
CARD = (30, 64, 175)  # indigo
CARD_EDGE = (23, 47, 130)
STRIPE = (79, 110, 210)  # lighter indigo band
CHIP = (250, 204, 21)  # gold
BADGE = (22, 163, 74)  # green
WHITE = (255, 255, 255)

SCALE = 8  # draw at 8x then shrink for clean edges


def _card(draw: ImageDraw.ImageDraw, x0: int, y0: int, x1: int, y1: int, s: int) -> None:
    r = 28 * s
    draw.rounded_rectangle((x0, y0, x1, y1), radius=r, fill=CARD, outline=CARD_EDGE, width=3 * s)
    h = y1 - y0
    # Stripe near the top, like the magnetic band on the back.
    draw.rectangle((x0, y0 + int(h * 0.22), x1, y0 + int(h * 0.36)), fill=STRIPE)
    # Chip, bottom-left.
    cw, ch = int((x1 - x0) * 0.2), int(h * 0.19)
    cx, cy = x0 + int((x1 - x0) * 0.1), y0 + int(h * 0.55)
    draw.rounded_rectangle((cx, cy, cx + cw, cy + ch), radius=5 * s, fill=CHIP)


def _badge(draw: ImageDraw.ImageDraw, cx: int, cy: int, radius: int, s: int) -> None:
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=BADGE)
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=WHITE, width=6 * s)
    w = 9 * s
    pts = [
        (cx - radius * 0.5, cy + radius * 0.02),
        (cx - radius * 0.12, cy + radius * 0.42),
        (cx + radius * 0.55, cy - radius * 0.4),
    ]
    draw.line(pts, fill=WHITE, width=w, joint="curve")


def icon(size: int) -> Image.Image:
    s = SCALE
    big = size * s
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # Card fills most of the square with an upright-ish 3:2 shape.
    w, h = int(big * 0.84), int(big * 0.56)
    x0, y0 = (big - w) // 2, int(big * 0.17)
    _card(d, x0, y0, x0 + w, y0 + h, s)
    _badge(d, x0 + w - int(big * 0.05), y0 + h - int(big * 0.03), int(big * 0.15), s)
    return img.resize((size, size), Image.LANCZOS)


def logo(width: int, height: int) -> Image.Image:
    s = SCALE
    bw, bh = width * s, height * s
    img = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    mark = icon(height).resize((bh, bh), Image.LANCZOS)
    img.alpha_composite(mark, (0, 0))
    text = "CardPerks"
    tx = int(bh * 0.92)
    avail = bw - tx - int(bw * 0.03)
    # Largest size whose wordmark fits the space left of the mark.
    px = int(bh * 0.42)
    font = _font(px)
    while px > 8 and d.textlength(text, font=font) > avail:
        px -= s
        font = _font(px)
    box = d.textbbox((0, 0), text, font=font)
    ty = (bh - (box[3] - box[1])) // 2 - box[1]
    d.text((tx, ty), text, font=font, fill=CARD)
    return img.resize((width, height), Image.LANCZOS)


def _font(px: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("segoeuib.ttf", "seguisb.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"):
        for folder in (Path("C:/Windows/Fonts"), Path("/usr/share/fonts/truetype/dejavu")):
            p = folder / name
            if p.exists():
                return ImageFont.truetype(str(p), px)
    return ImageFont.load_default()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    icon(256).save(OUT / "icon.png")
    icon(512).save(OUT / "icon@2x.png")
    logo(256, 128).save(OUT / "logo.png")
    logo(512, 256).save(OUT / "logo@2x.png")
    for p in sorted(OUT.iterdir()):
        print(p.name, Image.open(p).size)


if __name__ == "__main__":
    main()
