from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from calibrate_blue_wall_grid import detect_points


def load_calibration(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    data = json.loads(path.read_text(encoding="utf-8"))
    camera_matrix = np.asarray(data["camera_matrix"], dtype=np.float64)
    distortion = np.asarray(data["distortion_coefficients"], dtype=np.float64)
    new_camera_matrix = np.asarray(data.get("new_camera_matrix", camera_matrix), dtype=np.float64)
    return camera_matrix, distortion, new_camera_matrix


def ideal_grid_points(rows: int, cols: int, cell_px: float, margin_px: float) -> np.ndarray:
    points = []
    for row in range(rows):
        for col in range(cols):
            points.append((margin_px + col * cell_px, margin_px + row * cell_px))
    return np.asarray(points, dtype=np.float32)


def draw_rectified_grid(image: np.ndarray, rows: int, cols: int, cell_px: int, margin_px: int) -> np.ndarray:
    out = image.copy()
    color = (0, 255, 255)
    for row in range(rows):
        y = int(round(margin_px + row * cell_px))
        cv2.line(out, (margin_px, y), (margin_px + (cols - 1) * cell_px, y), color, 1, cv2.LINE_AA)
    for col in range(cols):
        x = int(round(margin_px + col * cell_px))
        cv2.line(out, (x, margin_px), (x, margin_px + (rows - 1) * cell_px), color, 1, cv2.LINE_AA)
    return out


def mesh_warp_grid(
    image: np.ndarray,
    source_points: np.ndarray,
    rows: int,
    cols: int,
    cell_px: int,
    margin_px: int,
    out_size: tuple[int, int],
) -> np.ndarray:
    out_width, out_height = out_size
    output = np.zeros((out_height, out_width, 3), dtype=image.dtype)
    source_grid = source_points.reshape(rows, cols, 2).astype(np.float32)

    for row in range(rows - 1):
        for col in range(cols - 1):
            src = np.asarray(
                [
                    source_grid[row, col],
                    source_grid[row, col + 1],
                    source_grid[row + 1, col + 1],
                    source_grid[row + 1, col],
                ],
                dtype=np.float32,
            )
            x0 = margin_px + col * cell_px
            y0 = margin_px + row * cell_px
            x1 = margin_px + (col + 1) * cell_px
            y1 = margin_px + (row + 1) * cell_px
            dst = np.asarray(
                [
                    [x0, y0],
                    [x1, y0],
                    [x1, y1],
                    [x0, y1],
                ],
                dtype=np.float32,
            )
            homography = cv2.getPerspectiveTransform(src, dst)
            warped = cv2.warpPerspective(image, homography, (out_width, out_height))
            mask = np.zeros((out_height, out_width), dtype=np.uint8)
            cv2.fillConvexPoly(mask, dst.astype(np.int32), 255)
            output[mask > 0] = warped[mask > 0]

    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--calibration", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--metadata-output", default=None)
    parser.add_argument("--cell-px", type=int, default=140)
    parser.add_argument("--margin-px", type=int, default=80)
    parser.add_argument("--alpha", type=float, default=0.4)
    parser.add_argument("--detect-on", choices=["auto", "raw", "undistorted"], default="auto")
    parser.add_argument("--warp-mode", choices=["homography", "mesh"], default="homography")
    args = parser.parse_args()

    image_path = Path(args.image)
    calibration_path = Path(args.calibration)
    output_path = Path(args.output)
    metadata_path = Path(args.metadata_output) if args.metadata_output else output_path.with_suffix(".json")

    image = cv2.imread(str(image_path))
    if image is None:
        raise RuntimeError(f"Could not read image: {image_path}")
    height, width = image.shape[:2]

    camera_matrix, distortion, saved_new_camera = load_calibration(calibration_path)
    if args.alpha >= 0:
        new_camera, roi = cv2.getOptimalNewCameraMatrix(
            camera_matrix,
            distortion,
            (width, height),
            args.alpha,
            (width, height),
        )
    else:
        new_camera = saved_new_camera
        roi = (0, 0, width, height)

    undistorted = cv2.undistort(image, camera_matrix, distortion, None, new_camera)
    detect_image = undistorted
    warp_image = undistorted
    image_points, shape, debug = detect_points(detect_image)
    detection_space = "undistorted"
    if image_points is None and args.detect_on == "auto":
        detect_image = image
        image_points, shape, debug = detect_points(detect_image)
        if image_points is not None:
            image_points = cv2.undistortPoints(
                image_points,
                camera_matrix,
                distortion,
                P=new_camera,
            )
        detection_space = "raw"
    elif args.detect_on == "raw":
        detect_image = image
        image_points, shape, debug = detect_points(detect_image)
        if image_points is not None:
            image_points = cv2.undistortPoints(
                image_points,
                camera_matrix,
                distortion,
                P=new_camera,
            )
        detection_space = "raw"
    if image_points is None:
        raise RuntimeError(f"Could not detect enough blue grid lines: {debug}")

    rows, cols = shape
    src = image_points.reshape(-1, 2).astype(np.float32)
    dst = ideal_grid_points(rows, cols, args.cell_px, args.margin_px)
    homography, inliers = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
    if homography is None:
        raise RuntimeError("Could not solve wall-plane homography")

    out_width = int(round(args.margin_px * 2 + (cols - 1) * args.cell_px))
    out_height = int(round(args.margin_px * 2 + (rows - 1) * args.cell_px))
    if args.warp_mode == "mesh":
        rectified = mesh_warp_grid(warp_image, src, rows, cols, args.cell_px, args.margin_px, (out_width, out_height))
    else:
        rectified = cv2.warpPerspective(warp_image, homography, (out_width, out_height))
    rectified_overlay = draw_rectified_grid(rectified, rows, cols, args.cell_px, args.margin_px)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), rectified)
    cv2.imwrite(str(output_path.with_name(output_path.stem + "_overlay.jpg")), rectified_overlay)

    metadata = {
        "source": "undistort_then_wall_plane_homography",
        "image": str(image_path),
        "calibration": str(calibration_path),
        "output": str(output_path),
        "overlay": str(output_path.with_name(output_path.stem + "_overlay.jpg")),
        "image_width": width,
        "image_height": height,
        "rectified_width": out_width,
        "rectified_height": out_height,
        "grid_rows": rows,
        "grid_cols": cols,
        "cell_px": args.cell_px,
        "margin_px": args.margin_px,
        "alpha": args.alpha,
        "detection_space": detection_space,
        "roi": [int(v) for v in roi],
        "homography": homography.tolist(),
        "warp_mode": args.warp_mode,
        "inlier_count": int(inliers.sum()) if inliers is not None else None,
        "point_count": int(len(src)),
        "debug": debug,
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"rectified_saved={output_path}")
    print(f"overlay_saved={output_path.with_name(output_path.stem + '_overlay.jpg')}")
    print(f"metadata_saved={metadata_path}")
    print(f"grid={rows}x{cols}")
    print(f"inliers={metadata['inlier_count']}/{metadata['point_count']}")


if __name__ == "__main__":
    main()
