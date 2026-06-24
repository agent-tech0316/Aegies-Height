"""Generate transparent logo chunks for LED sign image import apps.

Some Bluetooth LED sign apps crop imported images instead of fitting a full
word. This script exports smaller transparent PNG chunks, so each upload can be
one letter, two letters, or a short segment.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


DEFAULT_FONT = "generated_assets/fonts/Oxanium-Bold.ttf"
DEFAULT_COLOR = "#5579f9"


def parse_hex_color(value: str) -> tuple[int, int, int]:
    cleaned = value.strip().lstrip("#")
    if len(cleaned) != 6:
        raise ValueError("Color must be a 6-digit hex value, for example #5579f9.")
    return tuple(int(cleaned[index : index + 2], 16) for index in (0, 2, 4))


def scale_color(color: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(round(channel * factor)))) for channel in color)


def text_bbox(text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int, int, int]:
    scratch = Image.new("L", (1, 1), 0)
    draw = ImageDraw.Draw(scratch)
    return draw.textbbox((0, 0), text, font=font, stroke_width=0)


def fit_font(text: str, *, font_path: Path, width: int, height: int, fill: float) -> ImageFont.FreeTypeFont:
    max_width = int(width * fill)
    max_height = int(height * fill)
    best = ImageFont.truetype(str(font_path), size=8)
    for size in range(8, height * 6):
        font = ImageFont.truetype(str(font_path), size=size)
        left, top, right, bottom = text_bbox(text, font)
        if right - left > max_width or bottom - top > max_height:
            break
        best = font
    return best


def render_chunk(
    text: str,
    *,
    font_path: Path,
    color: tuple[int, int, int],
    width: int,
    height: int,
    fill: float,
    hard_pixels: bool,
) -> Image.Image:
    scale = 8
    high_width = width * scale
    high_height = height * scale
    high_font = fit_font(text, font_path=font_path, width=high_width, height=high_height, fill=fill)

    mask = Image.new("L", (high_width, high_height), 0)
    draw = ImageDraw.Draw(mask)
    left, top, right, bottom = text_bbox(text, high_font)
    text_width = right - left
    text_height = bottom - top
    x = (high_width - text_width) // 2 - left
    y = (high_height - text_height) // 2 - top - int(high_height * 0.02)
    draw.text((x, y), text, font=high_font, fill=255)

    tiny_mask = mask.resize((width, height), Image.Resampling.LANCZOS)
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    pixels = image.load()
    mask_pixels = tiny_mask.load()

    for yy in range(height):
        shade = 1.0 - 0.26 * (yy / max(1, height - 1))
        shaded = scale_color(color, shade)
        edge = scale_color(color, 0.28)
        for xx in range(width):
            alpha = int(mask_pixels[xx, yy])
            if hard_pixels:
                if alpha >= 96:
                    pixels[xx, yy] = (*color, 255)
            else:
                if alpha >= 118:
                    pixels[xx, yy] = (*shaded, 255)
                elif alpha >= 32:
                    pixels[xx, yy] = (*edge, max(110, alpha))

    if not hard_pixels:
        for yy in range(1, height):
            for xx in range(width):
                if mask_pixels[xx, yy] >= 118 and mask_pixels[xx, yy - 1] < 42:
                    pixels[xx, yy] = (*scale_color(color, 1.18), 255)

    return image


def save_preview(image: Image.Image, output: Path, *, scale: int) -> None:
    preview = Image.new("RGBA", image.size, (0, 0, 0, 255))
    preview.alpha_composite(image)
    preview = preview.convert("RGB")
    preview = preview.resize((image.width * scale, image.height * scale), Image.Resampling.NEAREST)
    preview.save(output)


def fixed_width_for_text(text: str, *, letter_width: int, pair_width: int, triple_width: int) -> int:
    if len(text) <= 1:
        return letter_width
    if len(text) == 2:
        return pair_width
    return triple_width


def write_chunk_set(
    chunks: list[str],
    *,
    name: str,
    output_dir: Path,
    font_path: Path,
    color: tuple[int, int, int],
    height: int,
    letter_width: int,
    pair_width: int,
    triple_width: int,
    fill: float,
    hard_pixels: bool,
    preview_scale: int,
) -> None:
    folder = output_dir / name
    folder.mkdir(parents=True, exist_ok=True)
    for index, chunk in enumerate(chunks, start=1):
        width = fixed_width_for_text(
            chunk,
            letter_width=letter_width,
            pair_width=pair_width,
            triple_width=triple_width,
        )
        image = render_chunk(
            chunk,
            font_path=font_path,
            color=color,
            width=width,
            height=height,
            fill=fill,
            hard_pixels=hard_pixels,
        )
        stem = f"{index:02d}_{chunk.lower()}"
        image_path = folder / f"{stem}.png"
        preview_path = folder / f"{stem}_preview.png"
        image.save(image_path)
        save_preview(image, preview_path, scale=preview_scale)
        print(f"wrote {image_path}")
        print(f"wrote {preview_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", default="AGENTECH")
    parser.add_argument("--font", default=DEFAULT_FONT)
    parser.add_argument("--color", default=DEFAULT_COLOR)
    parser.add_argument("--output-dir", default="generated_assets/led_sign_oxanium_transparent")
    parser.add_argument("--height", type=int, default=32)
    parser.add_argument("--letter-width", type=int, default=32)
    parser.add_argument("--pair-width", type=int, default=48)
    parser.add_argument("--triple-width", type=int, default=64)
    parser.add_argument("--fill", type=float, default=0.82)
    parser.add_argument("--soft", action="store_true", help="Use anti-aliased soft edges instead of hard LED pixels.")
    parser.add_argument("--preview-scale", type=int, default=10)
    args = parser.parse_args()

    text = args.text.upper()
    font_path = Path(args.font)
    if not font_path.exists():
        raise RuntimeError(f"Font not found: {font_path}")

    color = parse_hex_color(args.color)
    output_dir = Path(args.output_dir)

    letters = list(text)
    adjacent_pairs = [text[index : index + 2] for index in range(len(text) - 1)]
    nonoverlap_pairs = [text[index : index + 2] for index in range(0, len(text), 2)]
    triples = [text[index : index + 3] for index in range(0, len(text), 3)]

    common = {
        "output_dir": output_dir,
        "font_path": font_path,
        "color": color,
        "height": args.height,
        "letter_width": args.letter_width,
        "pair_width": args.pair_width,
        "triple_width": args.triple_width,
        "fill": args.fill,
        "hard_pixels": not args.soft,
        "preview_scale": args.preview_scale,
    }
    write_chunk_set(letters, name="single_letters", **common)
    write_chunk_set(adjacent_pairs, name="overlap_pairs", **common)
    write_chunk_set(nonoverlap_pairs, name="nonoverlap_pairs", **common)
    write_chunk_set(triples, name="three_letter_chunks", **common)


if __name__ == "__main__":
    main()
