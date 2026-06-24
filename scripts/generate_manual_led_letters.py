"""Generate hand-tuned hard-pixel AGENTECH letters for LED sign imports."""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


GLYPHS = {
    "A": [
        "00011111000",
        "00111111100",
        "01110001110",
        "01100000110",
        "11000000011",
        "11000000011",
        "11111111111",
        "11111111111",
        "11000000011",
        "11000000011",
        "11000000011",
        "11000000011",
        "11000000011",
    ],
    "G": [
        "00111111100",
        "01111111110",
        "11100000110",
        "11000000000",
        "11000000000",
        "11000111111",
        "11000111111",
        "11000000011",
        "11000000011",
        "11100000111",
        "01111111110",
        "00111111100",
        "00000000000",
    ],
    "E": [
        "11111111111",
        "11111111111",
        "11000000000",
        "11000000000",
        "11000000000",
        "11111111100",
        "11111111100",
        "11000000000",
        "11000000000",
        "11000000000",
        "11111111111",
        "11111111111",
        "00000000000",
    ],
    "N": [
        "11000000011",
        "11100000011",
        "11110000011",
        "11011000011",
        "11011100011",
        "11001110011",
        "11000111011",
        "11000011111",
        "11000001111",
        "11000000111",
        "11000000011",
        "11000000011",
        "11000000011",
    ],
    "T": [
        "11111111111",
        "11111111111",
        "00001110000",
        "00001110000",
        "00001110000",
        "00001110000",
        "00001110000",
        "00001110000",
        "00001110000",
        "00001110000",
        "00001110000",
        "00001110000",
        "00001110000",
    ],
    "C": [
        "00111111100",
        "01111111110",
        "11100000110",
        "11000000000",
        "11000000000",
        "11000000000",
        "11000000000",
        "11000000000",
        "11000000000",
        "11100000110",
        "01111111110",
        "00111111100",
        "00000000000",
    ],
    "H": [
        "11000000011",
        "11000000011",
        "11000000011",
        "11000000011",
        "11000000011",
        "11111111111",
        "11111111111",
        "11000000011",
        "11000000011",
        "11000000011",
        "11000000011",
        "11000000011",
        "11000000011",
    ],
}


def parse_hex_color(value: str) -> tuple[int, int, int]:
    cleaned = value.strip().lstrip("#")
    return tuple(int(cleaned[index : index + 2], 16) for index in (0, 2, 4))


def compose(text: str, *, color: tuple[int, int, int], pad: int, spacing: int) -> Image.Image:
    rows = max(len(GLYPHS[letter]) for letter in text)
    widths = [len(GLYPHS[letter][0]) for letter in text]
    width = sum(widths) + spacing * (len(text) - 1) + pad * 2
    height = rows + pad * 2
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    pixels = image.load()

    x = pad
    for letter, glyph_width in zip(text, widths):
        glyph = GLYPHS[letter]
        y_offset = pad + (rows - len(glyph)) // 2
        for y, row in enumerate(glyph):
            for gx, value in enumerate(row):
                if value == "1":
                    pixels[x + gx, y_offset + y] = (*color, 255)
        x += glyph_width + spacing
    return image


def save_preview(image: Image.Image, path: Path, *, scale: int) -> None:
    preview = Image.new("RGBA", image.size, (0, 0, 0, 255))
    preview.alpha_composite(image)
    preview = preview.convert("RGB").resize(
        (image.width * scale, image.height * scale),
        Image.Resampling.NEAREST,
    )
    preview.save(path)


def write_set(chunks: list[str], *, name: str, output_dir: Path, color: tuple[int, int, int], pad: int, spacing: int) -> None:
    folder = output_dir / name
    folder.mkdir(parents=True, exist_ok=True)
    for index, chunk in enumerate(chunks, start=1):
        image = compose(chunk, color=color, pad=pad, spacing=spacing)
        stem = f"{index:02d}_{chunk.lower()}"
        image_path = folder / f"{stem}.png"
        preview_path = folder / f"{stem}_preview.png"
        image.save(image_path)
        save_preview(image, preview_path, scale=12)
        print(f"wrote {image_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", default="AGENTECH")
    parser.add_argument("--color", default="#5579f9")
    parser.add_argument("--output-dir", default="generated_assets/led_sign_manual_hard")
    parser.add_argument("--pad", type=int, default=1)
    parser.add_argument("--spacing", type=int, default=1)
    args = parser.parse_args()

    text = args.text.upper()
    color = parse_hex_color(args.color)
    output_dir = Path(args.output_dir)

    letters = list(text)
    nonoverlap_pairs = [text[index : index + 2] for index in range(0, len(text), 2)]
    overlap_pairs = [text[index : index + 2] for index in range(len(text) - 1)]

    write_set(letters, name="single_letters", output_dir=output_dir, color=color, pad=args.pad, spacing=args.spacing)
    write_set(nonoverlap_pairs, name="nonoverlap_pairs", output_dir=output_dir, color=color, pad=args.pad, spacing=args.spacing)
    write_set(overlap_pairs, name="overlap_pairs", output_dir=output_dir, color=color, pad=args.pad, spacing=args.spacing)


if __name__ == "__main__":
    main()
