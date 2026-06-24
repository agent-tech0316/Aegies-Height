"""Split the official AGENTECH logo image into transparent upload chunks.

This keeps the actual logo pixels instead of redrawing the letters. It removes
the black background, finds the real letter bounds, and writes single-letter
and multi-letter chunks for LED sign app imports.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


LETTER_NAMES = list("AGENTECH")


def content_alpha(pixel: tuple[int, int, int, int], *, threshold: int) -> int:
    r, g, b, a = pixel
    brightness = max(r, g, b)
    if a == 0 or brightness <= threshold or b <= threshold:
        return 0
    # Preserve the original blue glow/shadow while removing the black canvas.
    return max(0, min(255, int((brightness - threshold) * 255 / max(1, 255 - threshold))))


def make_transparent(image: Image.Image, *, threshold: int) -> Image.Image:
    src = image.convert("RGBA")
    out = Image.new("RGBA", src.size, (0, 0, 0, 0))
    src_px = src.load()
    out_px = out.load()
    for y in range(src.height):
        for x in range(src.width):
            r, g, b, a = src_px[x, y]
            alpha = content_alpha((r, g, b, a), threshold=threshold)
            if alpha:
                out_px[x, y] = (r, g, b, alpha)
    return out


def column_has_content(image: Image.Image, x: int, *, threshold: int) -> bool:
    for y in range(image.height):
        if image.getpixel((x, y))[3] > threshold:
            return True
    return False


def row_has_content(image: Image.Image, y: int, *, threshold: int) -> bool:
    for x in range(image.width):
        if image.getpixel((x, y))[3] > threshold:
            return True
    return False


def find_runs(values: list[int], *, min_gap: int) -> list[tuple[int, int]]:
    if not values:
        return []
    runs: list[tuple[int, int]] = []
    start = prev = values[0]
    for value in values[1:]:
        if value - prev > min_gap:
            runs.append((start, prev))
            start = value
        prev = value
    runs.append((start, prev))
    return runs


def bounds_for_xrange(image: Image.Image, x0: int, x1: int, *, alpha_threshold: int, pad: int) -> tuple[int, int, int, int]:
    rows = []
    for y in range(image.height):
        for x in range(x0, x1 + 1):
            if image.getpixel((x, y))[3] > alpha_threshold:
                rows.append(y)
                break
    if not rows:
        return x0, 0, x1 + 1, image.height
    left = max(0, x0 - pad)
    top = max(0, min(rows) - pad)
    right = min(image.width, x1 + 1 + pad)
    bottom = min(image.height, max(rows) + 1 + pad)
    return left, top, right, bottom


def save_preview(chunk: Image.Image, path: Path, *, scale: int) -> None:
    preview = Image.new("RGBA", chunk.size, (0, 0, 0, 255))
    preview.alpha_composite(chunk)
    preview = preview.convert("RGB").resize(
        (chunk.width * scale, chunk.height * scale),
        Image.Resampling.NEAREST,
    )
    preview.save(path)


def save_chunk(
    image: Image.Image,
    *,
    x0: int,
    x1: int,
    name: str,
    output_dir: Path,
    alpha_threshold: int,
    pad: int,
    preview_scale: int,
) -> None:
    bounds = bounds_for_xrange(image, x0, x1, alpha_threshold=alpha_threshold, pad=pad)
    chunk = image.crop(bounds)
    output_dir.mkdir(parents=True, exist_ok=True)
    image_path = output_dir / f"{name}.png"
    preview_path = output_dir / f"{name}_preview.png"
    chunk.save(image_path)
    save_preview(chunk, preview_path, scale=preview_scale)
    print(f"wrote {image_path} ({chunk.width}x{chunk.height})")


def resized_copy(path: Path, *, target_height: int) -> Path:
    image = Image.open(path).convert("RGBA")
    ratio = target_height / image.height
    width = max(1, round(image.width * ratio))
    resized = image.resize((width, target_height), Image.Resampling.LANCZOS)
    output = path.with_name(path.stem + f"_h{target_height}.png")
    resized.save(output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        default=r"C:\Users\wesle\AppData\Local\Temp\codex-clipboard-59351ed6-5e76-49ab-8667-e8c9aa3723ae.png",
    )
    parser.add_argument("--output-dir", default="generated_assets/official_agentech_logo_chunks")
    parser.add_argument("--background-threshold", type=int, default=14)
    parser.add_argument("--alpha-threshold", type=int, default=18)
    parser.add_argument("--pad", type=int, default=6)
    parser.add_argument("--preview-scale", type=int, default=4)
    parser.add_argument("--resized-heights", nargs="*", type=int, default=[32, 24, 16])
    args = parser.parse_args()

    source = Path(args.source)
    output_dir = Path(args.output_dir)
    logo = make_transparent(Image.open(source), threshold=args.background_threshold)

    xs = [
        x
        for x in range(logo.width)
        if column_has_content(logo, x, threshold=args.alpha_threshold)
    ]
    runs = find_runs(xs, min_gap=2)
    if len(runs) != len(LETTER_NAMES):
        raise RuntimeError(f"Expected 8 letter runs, found {len(runs)}: {runs}")

    single_dir = output_dir / "single_letters"
    for index, ((x0, x1), letter) in enumerate(zip(runs, LETTER_NAMES), start=1):
        save_chunk(
            logo,
            x0=x0,
            x1=x1,
            name=f"{index:02d}_{letter.lower()}",
            output_dir=single_dir,
            alpha_threshold=args.alpha_threshold,
            pad=args.pad,
            preview_scale=args.preview_scale,
        )

    nonoverlap_dir = output_dir / "nonoverlap_pairs"
    for out_index, start_index in enumerate(range(0, len(runs), 2), start=1):
        chunk_name = "".join(LETTER_NAMES[start_index : start_index + 2]).lower()
        save_chunk(
            logo,
            x0=runs[start_index][0],
            x1=runs[min(start_index + 1, len(runs) - 1)][1],
            name=f"{out_index:02d}_{chunk_name}",
            output_dir=nonoverlap_dir,
            alpha_threshold=args.alpha_threshold,
            pad=args.pad,
            preview_scale=args.preview_scale,
        )

    overlap_dir = output_dir / "overlap_pairs"
    for index in range(len(runs) - 1):
        chunk_name = "".join(LETTER_NAMES[index : index + 2]).lower()
        save_chunk(
            logo,
            x0=runs[index][0],
            x1=runs[index + 1][1],
            name=f"{index + 1:02d}_{chunk_name}",
            output_dir=overlap_dir,
            alpha_threshold=args.alpha_threshold,
            pad=args.pad,
            preview_scale=args.preview_scale,
        )

    full_dir = output_dir / "full"
    save_chunk(
        logo,
        x0=runs[0][0],
        x1=runs[-1][1],
        name="agentech_official",
        output_dir=full_dir,
        alpha_threshold=args.alpha_threshold,
        pad=args.pad,
        preview_scale=args.preview_scale,
    )

    for height in args.resized_heights:
        for image_path in output_dir.rglob("*.png"):
            if image_path.name.endswith("_preview.png") or f"_h{height}" in image_path.stem:
                continue
            resized_copy(image_path, target_height=height)


if __name__ == "__main__":
    main()
