"""Generate pixel-art logo images for the small Bluetooth LED sign app.

The sign's phone app can usually import pictures even when the sign itself is
not programmable over USB. This script creates exact-size PNGs and enlarged
previews for common LED matrix resolutions.

Example:

  python scripts/generate_led_logo_pixels.py --text AGENTECH
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


DEFAULT_SIZES = ["64x16", "96x16", "96x32", "128x32", "160x32", "192x48"]
DEFAULT_FONTS = [
    r"C:\Windows\Fonts\bahnschrift.ttf",
    r"C:\Windows\Fonts\impact.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
]


def parse_size(value: str) -> tuple[int, int]:
    width, height = value.lower().split("x", 1)
    return int(width), int(height)


def parse_hex_color(value: str) -> tuple[int, int, int]:
    cleaned = value.strip().lstrip("#")
    if len(cleaned) != 6:
        raise ValueError("Color must be a 6-digit hex value, for example #5579f9.")
    return tuple(int(cleaned[index : index + 2], 16) for index in (0, 2, 4))


def scale_color(color: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(round(channel * factor)))) for channel in color)


def load_font(path: str | None, size: int) -> ImageFont.FreeTypeFont:
    candidates = [path] if path else []
    candidates.extend(DEFAULT_FONTS)
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    raise RuntimeError("Could not find a usable TrueType font. Pass --font PATH.")


def text_bbox(text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int, int, int]:
    scratch = Image.new("L", (1, 1), 0)
    draw = ImageDraw.Draw(scratch)
    return draw.textbbox((0, 0), text, font=font, stroke_width=0)


def fit_font(
    text: str,
    *,
    canvas_width: int,
    canvas_height: int,
    font_path: str | None,
    width_fill: float = 0.96,
    height_fill: float = 0.82,
) -> ImageFont.FreeTypeFont:
    # Render high resolution first, then shrink to the matrix size. This keeps
    # the final LED pixels readable while preserving the AGENTECH gradient feel.
    high_width = canvas_width * 8
    high_height = canvas_height * 8
    max_text_width = int(high_width * width_fill)
    max_text_height = int(high_height * height_fill)

    best = load_font(font_path, 8)
    for size in range(8, high_height * 2):
        font = load_font(font_path, size)
        left, top, right, bottom = text_bbox(text, font)
        if right - left > max_text_width or bottom - top > max_text_height:
            break
        best = font
    return best


def draw_logo(text: str, *, width: int, height: int, font_path: str | None) -> Image.Image:
    scale = 8
    high_width = width * scale
    high_height = height * scale

    mask = Image.new("L", (high_width, high_height), 0)
    draw = ImageDraw.Draw(mask)
    font = fit_font(text, canvas_width=width, canvas_height=height, font_path=font_path)
    left, top, right, bottom = text_bbox(text, font)
    text_width = right - left
    text_height = bottom - top
    x = (high_width - text_width) // 2 - left
    y = (high_height - text_height) // 2 - top - int(high_height * 0.04)

    shadow = Image.new("L", (high_width, high_height), 0)
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.text((x + scale, y + scale), text, font=font, fill=120)
    shadow = shadow.filter(ImageFilter.BoxBlur(scale * 0.55))

    draw.text((x, y), text, font=font, fill=255)

    gradient = Image.new("RGB", (high_width, high_height), (0, 0, 0))
    pixels = gradient.load()
    for yy in range(high_height):
        t = yy / max(1, high_height - 1)
        if t < 0.36:
            local = t / 0.36
            color = (
                int(82 - 20 * local),
                int(119 - 42 * local),
                int(255 - 35 * local),
            )
        else:
            local = (t - 0.36) / 0.64
            color = (
                int(56 - 45 * local),
                int(82 - 66 * local),
                int(214 - 166 * local),
            )
        for xx in range(high_width):
            pixels[xx, yy] = color

    image = Image.new("RGB", (high_width, high_height), (0, 0, 0))
    shadow_rgb = Image.new("RGB", (high_width, high_height), (0, 0, 22))
    image.paste(shadow_rgb, mask=shadow)
    image.paste(gradient, mask=mask)

    # Bright top edge, similar to the reference image but still LED-friendly.
    highlight = Image.new("L", (high_width, high_height), 0)
    highlight_draw = ImageDraw.Draw(highlight)
    highlight_draw.text((x, y - max(1, scale // 2)), text, font=font, fill=55)
    highlight = Image.eval(highlight, lambda value: min(value, 70))
    image.paste(Image.new("RGB", (high_width, high_height), (114, 151, 255)), mask=highlight)

    return image.resize((width, height), Image.Resampling.LANCZOS)


def draw_crisp_logo(
    text: str,
    *,
    width: int,
    height: int,
    font_path: str | None,
    width_fill: float,
    height_fill: float,
    color: tuple[int, int, int],
) -> Image.Image:
    scale = 8
    high_width = width * scale
    high_height = height * scale

    mask = Image.new("L", (high_width, high_height), 0)
    draw = ImageDraw.Draw(mask)
    font = fit_font(
        text,
        canvas_width=width,
        canvas_height=height,
        font_path=font_path,
        width_fill=width_fill,
        height_fill=height_fill,
    )
    left, top, right, bottom = text_bbox(text, font)
    text_width = right - left
    text_height = bottom - top
    x = (high_width - text_width) // 2 - left
    y = (high_height - text_height) // 2 - top - int(high_height * 0.03)
    draw.text((x, y), text, font=font, fill=255)

    tiny_mask = mask.resize((width, height), Image.Resampling.LANCZOS)
    image = Image.new("RGB", (width, height), (0, 0, 0))
    pixels = image.load()
    mask_pixels = tiny_mask.load()

    for yy in range(height):
        shade = 1.0 - 0.32 * (yy / max(1, height - 1))
        shaded_color = scale_color(color, shade)

        for xx in range(width):
            alpha = mask_pixels[xx, yy]
            if alpha >= 118:
                pixels[xx, yy] = shaded_color
            elif alpha >= 42:
                pixels[xx, yy] = scale_color(color, 0.22)

    # Single-pixel highlight on the top edge, no blur.
    for yy in range(1, height):
        for xx in range(width):
            if mask_pixels[xx, yy] >= 118 and mask_pixels[xx, yy - 1] < 42:
                pixels[xx, yy] = scale_color(color, 1.18)

    return image


def save_preview(image: Image.Image, path: Path, *, scale: int) -> None:
    preview = image.resize((image.width * scale, image.height * scale), Image.Resampling.NEAREST)
    preview.save(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", default="AGENTECH")
    parser.add_argument("--sizes", nargs="+", default=DEFAULT_SIZES, help="Matrix sizes like 64x16 96x32.")
    parser.add_argument("--font", default=None, help="Optional TrueType font path.")
    parser.add_argument("--style", choices=["crisp", "glossy"], default="crisp")
    parser.add_argument("--color", default="#5579f9", help="Main text color, for example #5579f9.")
    parser.add_argument("--width-fill", type=float, default=0.90)
    parser.add_argument("--height-fill", type=float, default=0.76)
    parser.add_argument("--output-dir", default="generated_assets/led_sign")
    parser.add_argument("--preview-scale", type=int, default=10)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    color = parse_hex_color(args.color)

    for raw_size in args.sizes:
        width, height = parse_size(raw_size)
        if args.style == "glossy":
            image = draw_logo(args.text, width=width, height=height, font_path=args.font)
        else:
            image = draw_crisp_logo(
                args.text,
                width=width,
                height=height,
                font_path=args.font,
                width_fill=args.width_fill,
                height_fill=args.height_fill,
                color=color,
            )
        image_path = output_dir / f"{args.text.lower()}_{args.style}_{width}x{height}.png"
        preview_path = output_dir / f"{args.text.lower()}_{args.style}_{width}x{height}_preview.png"
        image.save(image_path)
        save_preview(image, preview_path, scale=args.preview_scale)
        print(f"wrote {image_path}")
        print(f"wrote {preview_path}")


if __name__ == "__main__":
    main()
