"""Draw the brand icon of the integration.

Run: .venv/bin/python scripts/make_icon.py

The icon is an original drawing: a rounded square, a lightning bolt and a
small slash mark. It writes icon.png (256 px) and icon@2x.png (512 px) into
custom_components/elektro_celje/brand/. The background around the badge is
transparent. The colours are a dark badge with a yellow bolt, so the icon
reads on both light and dark pages and no dark variant is needed.
"""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).parent.parent / "custom_components" / "elektro_celje" / "brand"
SCALE = 4  # Draw large, then shrink for smooth edges.

BADGE = (38, 50, 86, 255)
RING = (255, 255, 255, 255)
BOLT = (255, 200, 40, 255)
SLASH = (240, 80, 70, 255)


def draw(size: int) -> Image.Image:
    big = size * SCALE
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def p(x: float, y: float) -> tuple[float, float]:
        return (x * big / 100, y * big / 100)

    d.rounded_rectangle([p(6, 6), p(94, 94)], radius=big * 0.22, fill=BADGE)
    d.rounded_rectangle(
        [p(6, 6), p(94, 94)], radius=big * 0.22, outline=RING, width=int(big * 0.02)
    )
    bolt = [(56, 14), (28, 54), (46, 54), (38, 86), (72, 42), (53, 42), (62, 14)]
    d.polygon([p(x, y) for x, y in bolt], fill=BOLT)
    # The slash says "off": power is cut.
    d.line([p(20, 80), p(80, 20)], fill=SLASH, width=int(big * 0.055))
    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    draw(256).save(OUT / "icon.png")
    draw(512).save(OUT / "icon@2x.png")
