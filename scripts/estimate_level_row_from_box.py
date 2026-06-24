"""Estimate the camera level row from a known-height cardboard box.

This uses OpenCV to detect the brown front face of the box, measures the
top/bottom image points, and converts the known box height into an estimated
same-height/level row for the robot camera.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def load_calibration(path: Path) -> tuple[np.ndarray, np.ndarray]:
    data = json.loads(path.read_text())
    camera_matrix = np.array(data["camera_matrix"], dtype=np.float64)
    distortion = np.array(data["distortion_coefficients"], dtype=np.float64).reshape(-1, 1)
    return camera_matrix, distortion


def order_quad(points: np.ndarray) -> np.ndarray:
    points = np.asarray(points, dtype=np.float32).reshape(4, 2)
    ordered = np.zeros((4, 2), dtype=np.float32)
    sums = points.sum(axis=1)
    diffs = np.diff(points, axis=1).reshape(-1)
    ordered[0] = points[np.argmin(sums)]  # top-left
    ordered[2] = points[np.argmax(sums)]  # bottom-right
    ordered[1] = points[np.argmin(diffs)]  # top-right
    ordered[3] = points[np.argmax(diffs)]  # bottom-left
    return ordered


def detect_cardboard_box(image: np.ndarray, roi_frac: tuple[float, float, float, float]) -> dict[str, object]:
    height, width = image.shape[:2]
    x0 = int(width * roi_frac[0])
    y0 = int(height * roi_frac[1])
    x1 = int(width * roi_frac[2])
    y1 = int(height * roi_frac[3])
    roi = image[y0:y1, x0:x1]

    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    # Cardboard: orange/brown hue with moderate saturation/value. This ignores
    # blue tape, white wall, and dark hallway.
    mask = cv2.inRange(hsv, np.array([5, 30, 45]), np.array([35, 215, 230]))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((23, 23), np.uint8))

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise RuntimeError("No cardboard-colored contour found. Try adjusting --roi.")

    contour = max(contours, key=cv2.contourArea)
    if cv2.contourArea(contour) < 5000:
        raise RuntimeError("Detected cardboard contour is too small.")

    hull = cv2.convexHull(contour)
    peri = cv2.arcLength(hull, True)
    approx = cv2.approxPolyDP(hull, 0.025 * peri, True)
    if len(approx) == 4:
        quad = approx.reshape(4, 2).astype(np.float32)
    else:
        quad = cv2.boxPoints(cv2.minAreaRect(contour)).astype(np.float32)

    quad[:, 0] += x0
    quad[:, 1] += y0
    quad = order_quad(quad)

    top_mid = (quad[0] + quad[1]) / 2.0
    bottom_mid = (quad[3] + quad[2]) / 2.0
    left_height = float(np.linalg.norm(quad[3] - quad[0]))
    right_height = float(np.linalg.norm(quad[2] - quad[1]))
    mid_height = float(np.linalg.norm(bottom_mid - top_mid))

    return {
        "roi_px": [x0, y0, x1, y1],
        "contour_area": float(cv2.contourArea(contour)),
        "mask": mask,
        "quad": quad,
        "top_mid": top_mid,
        "bottom_mid": bottom_mid,
        "left_height_px": left_height,
        "right_height_px": right_height,
        "mid_height_px": mid_height,
    }


def estimate_level_row(
    *,
    top_mid: np.ndarray,
    bottom_mid: np.ndarray,
    camera_height_cm: float,
    box_height_cm: float,
    camera_matrix: np.ndarray | None,
    distortion: np.ndarray | None,
) -> dict[str, float | str]:
    t = camera_height_cm / box_height_cm
    if camera_matrix is None or distortion is None:
        level_y = float(bottom_mid[1] + t * (top_mid[1] - bottom_mid[1]))
        return {
            "space": "raw_pixel_linear",
            "level_row_y": level_y,
            "top_y": float(top_mid[1]),
            "bottom_y": float(bottom_mid[1]),
        }

    pts = np.array([[top_mid], [bottom_mid]], dtype=np.float64)
    undistorted = cv2.undistortPoints(pts, camera_matrix, distortion).reshape(2, 2)
    top_norm, bottom_norm = undistorted
    level_norm = bottom_norm + t * (top_norm - bottom_norm)
    fx = float(camera_matrix[0, 0])
    fy = float(camera_matrix[1, 1])
    cx = float(camera_matrix[0, 2])
    cy = float(camera_matrix[1, 2])
    return {
        "space": "undistorted_pixel",
        "level_row_y": float(fy * level_norm[1] + cy),
        "level_col_x": float(fx * level_norm[0] + cx),
        "top_undistorted_y": float(fy * top_norm[1] + cy),
        "bottom_undistorted_y": float(fy * bottom_norm[1] + cy),
    }


def draw_overlay(
    image: np.ndarray,
    detection: dict[str, object],
    level: dict[str, float | str],
    output: Path,
    *,
    box_height_cm: float,
    camera_height_cm: float,
) -> None:
    overlay = image.copy()
    quad = detection["quad"].astype(np.int32)
    top_mid = detection["top_mid"]
    bottom_mid = detection["bottom_mid"]
    cv2.polylines(overlay, [quad], True, (0, 255, 255), 4)
    cv2.circle(overlay, tuple(np.round(top_mid).astype(int)), 8, (0, 255, 0), -1)
    cv2.circle(overlay, tuple(np.round(bottom_mid).astype(int)), 8, (0, 0, 255), -1)

    raw_level_y = float(bottom_mid[1] + (camera_height_cm / box_height_cm) * (top_mid[1] - bottom_mid[1]))
    cv2.line(overlay, (0, int(round(raw_level_y))), (overlay.shape[1], int(round(raw_level_y))), (255, 0, 255), 3)
    label = f"raw level row ~ {raw_level_y:.1f}px"
    if level["space"] == "undistorted_pixel":
        label += f" | undistorted ~ {float(level['level_row_y']):.1f}px"
    cv2.putText(overlay, label, (35, max(35, int(round(raw_level_y)) - 18)), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (255, 0, 255), 2)
    cv2.putText(
        overlay,
        f"OpenCV box: {box_height_cm:.1f}cm, camera height assumed {camera_height_cm:.1f}cm",
        (35, 55),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.85,
        (0, 255, 255),
        2,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output), overlay)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--calibration")
    parser.add_argument("--output", required=True)
    parser.add_argument("--json-output")
    parser.add_argument("--box-height-cm", type=float, default=39.5)
    parser.add_argument("--camera-height-cm", type=float, default=33.0)
    parser.add_argument(
        "--roi",
        default="0.45,0.50,0.92,1.00",
        help="ROI fractions x0,y0,x1,y1. Default searches lower/right image.",
    )
    args = parser.parse_args()

    image_path = Path(args.image)
    image = cv2.imread(str(image_path))
    if image is None:
        raise RuntimeError(f"Could not read image: {image_path}")

    roi_frac = tuple(float(part) for part in args.roi.split(","))
    if len(roi_frac) != 4:
        raise RuntimeError("--roi must be x0,y0,x1,y1")

    camera_matrix = distortion = None
    if args.calibration:
        camera_matrix, distortion = load_calibration(Path(args.calibration))

    detection = detect_cardboard_box(image, roi_frac)
    level = estimate_level_row(
        top_mid=detection["top_mid"],
        bottom_mid=detection["bottom_mid"],
        camera_height_cm=args.camera_height_cm,
        box_height_cm=args.box_height_cm,
        camera_matrix=camera_matrix,
        distortion=distortion,
    )

    output = Path(args.output)
    draw_overlay(
        image,
        detection,
        level,
        output,
        box_height_cm=args.box_height_cm,
        camera_height_cm=args.camera_height_cm,
    )

    result = {
        "image": str(image_path),
        "output": str(output),
        "box_height_cm": args.box_height_cm,
        "camera_height_cm": args.camera_height_cm,
        "roi_px": detection["roi_px"],
        "contour_area": detection["contour_area"],
        "box_quad_px": detection["quad"].round(2).tolist(),
        "box_top_mid_px": detection["top_mid"].round(2).tolist(),
        "box_bottom_mid_px": detection["bottom_mid"].round(2).tolist(),
        "box_left_height_px": detection["left_height_px"],
        "box_right_height_px": detection["right_height_px"],
        "box_mid_height_px": detection["mid_height_px"],
        "level": level,
    }
    if args.json_output:
        Path(args.json_output).write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
