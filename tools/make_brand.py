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

# Matte charcoal card with a brass chip and an amber check: dark and a little
# worn-in rather than bank-brochure blue. Colour is identity here, not meaning, so
# nothing from the dashboard's captured/forfeited scheme is reused.
CARD = (36, 39, 44)  # charcoal
CARD_EDGE = (20, 22, 26)
SHEEN = (52, 56, 63)  # diagonal band across the face
CHIP = (201, 154, 62)  # brass
CHIP_EDGE = (150, 110, 40)
BADGE = (240, 162, 42)  # amber
BADGE_EDGE = (28, 30, 34)
INK = (28, 30, 34)  # check mark and wordmark
TILT = 8  # degrees; a card tossed on a table, not filed in a drawer

SCALE = 8  # draw at 8x then shrink for clean edges


def _card_layer(w: int, h: int, s: int) -> Image.Image:
    """The card face by itself, before tilting."""
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    r = 22 * s
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=r, fill=CARD, outline=CARD_EDGE, width=3 * s)
    # Diagonal sheen, clipped to the card shape.
    sheen = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sheen)
    sd.polygon(
        [(int(w * 0.30), 0), (int(w * 0.62), 0), (int(w * 0.32), h), (0, h), (0, int(h * 0.55))],
        fill=SHEEN,
    )
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=r, fill=255)
    layer.paste(sheen, (0, 0), Image.composite(mask, Image.new("L", (w, h), 0), sheen.split()[3]))
    # Brass chip, upper-left, with the usual contact grooves.
    cw, ch = int(w * 0.2), int(h * 0.22)
    cx, cy = int(w * 0.1), int(h * 0.3)
    d.rounded_rectangle(
        (cx, cy, cx + cw, cy + ch), radius=4 * s, fill=CHIP, outline=CHIP_EDGE, width=2 * s
    )
    d.line((cx, cy + ch // 2, cx + cw, cy + ch // 2), fill=CHIP_EDGE, width=2 * s)
    d.line((cx + cw // 3, cy, cx + cw // 3, cy + ch), fill=CHIP_EDGE, width=2 * s)
    d.line((cx + 2 * cw // 3, cy, cx + 2 * cw // 3, cy + ch), fill=CHIP_EDGE, width=2 * s)
    # Embossed number blocks along the bottom.
    by = int(h * 0.72)
    bw, gap = int(w * 0.16), int(w * 0.05)
    x = cx
    for _ in range(4):
        d.rounded_rectangle((x, by, x + bw, by + int(h * 0.07)), radius=2 * s, fill=CARD_EDGE)
        x += bw + gap
    return layer


def _badge(draw: ImageDraw.ImageDraw, cx: int, cy: int, radius: int, s: int) -> None:
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=BADGE)
    draw.ellipse(
        (cx - radius, cy - radius, cx + radius, cy + radius), outline=BADGE_EDGE, width=5 * s
    )
    w = 9 * s
    pts = [
        (cx - radius * 0.5, cy + radius * 0.02),
        (cx - radius * 0.12, cy + radius * 0.42),
        (cx + radius * 0.55, cy - radius * 0.4),
    ]
    draw.line(pts, fill=INK, width=w, joint="curve")


def icon(size: int) -> Image.Image:
    s = SCALE
    big = size * s
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    w, h = int(big * 0.78), int(big * 0.5)
    card = _card_layer(w, h, s).rotate(TILT, resample=Image.BICUBIC, expand=True)
    cx = (big - card.width) // 2
    cy = (big - card.height) // 2 - int(big * 0.03)
    img.alpha_composite(card, (cx, cy))
    d = ImageDraw.Draw(img)
    _badge(d, int(big * 0.78), int(big * 0.74), int(big * 0.15), s)
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
    d.text((tx, ty), text, font=font, fill=INK)
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
