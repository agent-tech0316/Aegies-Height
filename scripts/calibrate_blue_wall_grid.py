from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def save_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def blue_mask(image: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([85, 35, 20]), np.array([135, 255, 255]))
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8), iterations=1)


def component_lines(mask: np.ndarray, axis: str) -> list[dict[str, object]]:
    if axis == "vertical":
        opened = cv2.morphologyEx(
            mask,
            cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_RECT, (9, 120)),
            iterations=1,
        )
    else:
        opened = cv2.morphologyEx(
            mask,
            cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_RECT, (120, 9)),
            iterations=1,
        )

    count, labels, stats, centroids = cv2.connectedComponentsWithStats(opened, 8)
    lines: list[dict[str, object]] = []
    for index in range(1, count):
        x, y, width, height, area = stats[index]
        if axis == "vertical":
            keep = height > 250 and area > 1500 and width < 260
            center = float(centroids[index][0])
        else:
            keep = width > 300 and area > 1500 and height < 160
            center = float(centroids[index][1])
        if not keep:
            continue
        ys, xs = np.where(labels == index)
        lines.append(
            {
                "center": center,
                "bbox": [int(x), int(y), int(width), int(height)],
                "area": int(area),
                "xs": xs.astype(np.float32),
                "ys": ys.astype(np.float32),
            }
        )
    return sorted(lines, key=lambda item: float(item["center"]))


def best_regular_run(lines: list[dict[str, object]], *, min_count: int, max_count: int) -> list[dict[str, object]]:
    if len(lines) < min_count:
        return []
    centers = np.array([float(line["center"]) for line in lines], dtype=np.float64)
    best: tuple[float, int, int] | None = None
    for count in range(min(max_count, len(lines)), min_count - 1, -1):
        for start in range(0, len(lines) - count + 1):
            seq = centers[start : start + count]
            gaps = np.diff(seq)
            if np.any(gaps < 70) or np.any(gaps > 360):
                continue
            cv = float(np.std(gaps) / max(1.0, np.mean(gaps)))
            span_bonus = -0.02 * count
            score = cv + span_bonus
            if best is None or score < best[0]:
                best = (score, start, count)
        if best is not None and best[2] == count:
            break
    if best is None:
        return []
    _, start, count = best
    return lines[start : start + count]


def centerline_poly(line: dict[str, object], axis: str):
    xs = line["xs"]
    ys = line["ys"]
    if axis == "vertical":
        keys = ys.astype(np.int32)
        centers = []
        for key in np.unique(keys):
            vals = xs[keys == key]
            if vals.size >= 3:
                centers.append((float(key), float(np.median(vals))))
        arr = np.asarray(centers, dtype=np.float64)
        deg = 2 if len(arr) >= 8 else 1
        return np.poly1d(np.polyfit(arr[:, 0], arr[:, 1], deg))

    keys = xs.astype(np.int32)
    centers = []
    for key in np.unique(keys):
        vals = ys[keys == key]
        if vals.size >= 3:
            centers.append((float(key), float(np.median(vals))))
    arr = np.asarray(centers, dtype=np.float64)
    deg = 2 if len(arr) >= 8 else 1
    return np.poly1d(np.polyfit(arr[:, 0], arr[:, 1], deg))


def intersection(vpoly, hpoly, y0: float) -> tuple[float, float]:
    y = float(y0)
    x = float(vpoly(y))
    for _ in range(8):
        y = float(hpoly(x))
        x = float(vpoly(y))
    return x, y


def detect_points(image: np.ndarray) -> tuple[np.ndarray | None, tuple[int, int], dict[str, object]]:
    mask = blue_mask(image)
    verticals = best_regular_run(component_lines(mask, "vertical"), min_count=6, max_count=8)
    horizontals = best_regular_run(component_lines(mask, "horizontal"), min_count=5, max_count=8)
    debug = {
        "vertical_centers": [round(float(line["center"]), 2) for line in verticals],
        "horizontal_centers": [round(float(line["center"]), 2) for line in horizontals],
    }
    if len(verticals) < 6 or len(horizontals) < 5:
        debug["accepted"] = False
        return None, (0, 0), debug

    vpolys = [centerline_poly(line, "vertical") for line in verticals]
    hpolys = [centerline_poly(line, "horizontal") for line in horizontals]
    points = []
    for hline, hpoly in zip(horizontals, hpolys):
        row = []
        y0 = float(hline["center"])
        for vpoly in vpolys:
            row.append(intersection(vpoly, hpoly, y0))
        points.append(row)
    pts = np.asarray(points, dtype=np.float32)
    debug["accepted"] = True
    debug["shape"] = [int(pts.shape[0]), int(pts.shape[1])]
    return pts.reshape(-1, 1, 2), (pts.shape[0], pts.shape[1]), debug


def object_points(rows: int, cols: int, square_size_cm: float) -> np.ndarray:
    obj = np.zeros((rows * cols, 3), dtype=np.float32)
    grid = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2)
    obj[:, :2] = grid.astype(np.float32) * float(square_size_cm)
    return obj


def run_calibration(
    object_sets: list[np.ndarray],
    image_sets: list[np.ndarray],
    image_size: tuple[int, int],
    flags: int,
):
    rms, camera_matrix, distortion, rvecs, tvecs = cv2.calibrateCamera(
        object_sets,
        image_sets,
        image_size,
        None,
        None,
        flags=flags,
    )
    per_view = []
    for obj, img, rvec, tvec in zip(object_sets, image_sets, rvecs, tvecs):
        projected, _ = cv2.projectPoints(obj, rvec, tvec, camera_matrix, distortion)
        err = cv2.norm(img, projected, cv2.NORM_L2) / max(1, len(projected))
        per_view.append(float(err))
    return rms, camera_matrix, distortion, rvecs, tvecs, per_view


def calibration_flags(model: str) -> tuple[int, list[str]]:
    if model == "default":
        return 0, []
    if model == "fix_k3":
        return cv2.CALIB_FIX_K3, ["CALIB_FIX_K3"]
    if model == "zero_tangent":
        return cv2.CALIB_ZERO_TANGENT_DIST, ["CALIB_ZERO_TANGENT_DIST"]
    if model == "zero_tangent_fix_k3":
        return (
            cv2.CALIB_ZERO_TANGENT_DIST | cv2.CALIB_FIX_K3,
            ["CALIB_ZERO_TANGENT_DIST", "CALIB_FIX_K3"],
        )
    if model == "rational":
        return cv2.CALIB_RATIONAL_MODEL, ["CALIB_RATIONAL_MODEL"]
    if model == "rational_zero_tangent":
        return (
            cv2.CALIB_RATIONAL_MODEL | cv2.CALIB_ZERO_TANGENT_DIST,
            ["CALIB_RATIONAL_MODEL", "CALIB_ZERO_TANGENT_DIST"],
        )
    raise ValueError(f"Unknown calibration model: {model}")


def annotate(image: np.ndarray, points: np.ndarray | None, debug: dict[str, object]) -> np.ndarray:
    out = image.copy()
    if points is not None:
        for index, point in enumerate(points.reshape(-1, 2), start=1):
            x, y = point
            cv2.circle(out, (int(round(x)), int(round(y))), 4, (0, 255, 255), -1)
            if index % 8 == 1:
                cv2.putText(out, str(index), (int(x) + 4, int(y) - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 2)
                cv2.putText(out, str(index), (int(x) + 4, int(y) - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
    text = "accepted" if debug.get("accepted") else "rejected"
    if "shape" in debug:
        text += f" {debug['shape'][0]}x{debug['shape'][1]}"
    cv2.putText(out, text, (24, 42), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 4, cv2.LINE_AA)
    cv2.putText(out, text, (24, 42), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 1, cv2.LINE_AA)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--debug-dir", default=None)
    parser.add_argument("--square-size-cm", type=float, default=15.0)
    parser.add_argument("--min-accepted", type=int, default=4)
    parser.add_argument("--prune-worst", type=int, default=6)
    parser.add_argument("--target-view-error-px", type=float, default=4.0)
    parser.add_argument(
        "--model",
        choices=[
            "default",
            "fix_k3",
            "zero_tangent",
            "zero_tangent_fix_k3",
            "rational",
            "rational_zero_tangent",
        ],
        default="fix_k3",
    )
    args = parser.parse_args()

    image_dir = Path(args.image_dir)
    output = Path(args.output)
    debug_dir = Path(args.debug_dir) if args.debug_dir else output.parent / "blue_grid_debug"
    debug_dir.mkdir(parents=True, exist_ok=True)

    object_sets = []
    image_sets = []
    accepted_names = []
    records = []
    image_size = None
    for path in sorted(image_dir.glob("*.jpg")) + sorted(image_dir.glob("*.png")):
        if (
            path.name.endswith("_components.jpg")
            or path.name.endswith("_grid_debug.jpg")
            or path.name.endswith("_undistorted_preview.jpg")
            or path.name == "contact_sheet.jpg"
        ):
            continue
        image = cv2.imread(str(path))
        if image is None:
            continue
        height, width = image.shape[:2]
        image_size = (width, height)
        points, shape, debug = detect_points(image)
        debug["image"] = str(path)
        records.append(debug)
        cv2.imwrite(str(debug_dir / f"{path.stem}_grid_debug.jpg"), annotate(image, points, debug))
        if points is None:
            continue
        rows, cols = shape
        object_sets.append(object_points(rows, cols, args.square_size_cm))
        image_sets.append(points)
        accepted_names.append(path.name)

    if image_size is None:
        raise RuntimeError(f"No readable images in {image_dir}")
    if len(image_sets) < args.min_accepted:
        raise RuntimeError(f"Need {args.min_accepted} accepted images, got {len(image_sets)}")

    flags, flag_names = calibration_flags(args.model)
    active = list(range(len(image_sets)))
    prune_log = []
    while True:
        active_objects = [object_sets[index] for index in active]
        active_images = [image_sets[index] for index in active]
        rms, camera_matrix, distortion, rvecs, tvecs, per_view = run_calibration(
            active_objects,
            active_images,
            image_size,
            flags,
        )
        worst_local = int(np.argmax(per_view))
        worst_error = per_view[worst_local]
        if (
            len(prune_log) >= args.prune_worst
            or len(active) <= args.min_accepted
            or worst_error <= args.target_view_error_px
        ):
            break
        removed_index = active.pop(worst_local)
        prune_log.append(
            {
                "removed": accepted_names[removed_index],
                "view_error_px": worst_error,
                "rms_before_remove": float(rms),
            }
        )

    accepted_names_final = [accepted_names[index] for index in active]
    per_view_report = [
        {"image": name, "view_error_px": error}
        for name, error in zip(accepted_names_final, per_view)
    ]

    fx = float(camera_matrix[0, 0])
    fy = float(camera_matrix[1, 1])
    width, height = image_size
    hfov = float(np.degrees(2.0 * np.arctan(width / (2.0 * fx))))
    vfov = float(np.degrees(2.0 * np.arctan(height / (2.0 * fy))))

    preview_src = cv2.imread(str(sorted(image_dir.glob("*.jpg"))[0]))
    new_camera, roi = cv2.getOptimalNewCameraMatrix(camera_matrix, distortion, image_size, 0.4, image_size)
    undistorted = cv2.undistort(preview_src, camera_matrix, distortion, None, new_camera)
    cv2.imwrite(str(output.with_name(output.stem + "_undistorted_preview.jpg")), undistorted)

    save_json(
        output,
        {
            "source": "blue_wall_grid_custom_intersections",
            "image_dir": str(image_dir),
            "image_width": width,
            "image_height": height,
            "detected_count": len(image_sets),
            "accepted_count": len(active),
            "rms_reprojection_error": float(rms),
            "per_view_errors": per_view_report,
            "prune_log": prune_log,
            "camera_matrix": camera_matrix.tolist(),
            "distortion_coefficients": distortion.reshape(-1).tolist(),
            "new_camera_matrix": new_camera.tolist(),
            "roi": [int(v) for v in roi],
            "horizontal_fov_deg": hfov,
            "vertical_fov_deg": vfov,
            "model": args.model,
            "flags": flag_names,
            "records": records,
        },
    )
    print(f"calibration_saved={output}")
    print(f"detected_count={len(image_sets)}")
    print(f"accepted_count={len(active)}")
    print(f"rms_reprojection_error={rms:.4f}")
    print(f"worst_view_error_px={max(per_view):.4f}")
    print(f"horizontal_fov_deg={hfov:.2f}")
    print(f"vertical_fov_deg={vfov:.2f}")
    print(f"debug_dir={debug_dir}")


if __name__ == "__main__":
    main()
