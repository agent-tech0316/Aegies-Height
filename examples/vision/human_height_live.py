"""Live human-only height estimate using dog camera + Pi HC-SR04.

Run this on the Raspberry Pi. The script only uses the ultrasonic distance
when YOLO detects a full-body person near the camera/sensor aim point. If it
sees no person, or the person is off-center/cut off, it ignores the distance
so walls, plants, and other objects do not become the height target.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import statistics
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

from height_calculator import (
    DEFAULT_HCSR04_ECHO_PIN,
    DEFAULT_HCSR04_TRIGGER_PIN,
    DEFAULT_MODEL,
    DEFAULT_RTSP_URL,
    PersonBox,
    capture_one_frame,
    detect_people_yolo,
    estimate_height_from_box_calibration,
    estimate_height_from_split_tilt_calibration,
    load_camera_calibration,
    pixel_y_for_vertical_ray_deg_calibration,
    read_hcsr04_distance_cm,
    require_cv2_numpy,
    vertical_ray_deg_from_pixel_calibration,
)


def choose_person(detections: list[PersonBox], person_index: int) -> PersonBox | None:
    if len(detections) <= person_index:
        return None
    return detections[person_index]


def gate_person(
    *,
    person: PersonBox | None,
    image_width: int,
    image_height: int,
    center_tolerance_ratio: float,
    edge_margin_px: float,
    min_height_ratio: float,
    max_height_ratio: float,
) -> tuple[bool, list[str]]:
    if person is None:
        return False, ["no_person_detected"]

    reasons: list[str] = []
    if person.top_y <= edge_margin_px:
        reasons.append("head_cut_off")
    if person.bottom_y >= image_height - edge_margin_px:
        reasons.append("feet_cut_off")

    height_ratio = person.height / float(image_height)
    if height_ratio < min_height_ratio:
        reasons.append("person_too_small_or_far")
    if height_ratio > max_height_ratio:
        reasons.append("person_too_large_or_close")

    center_error_ratio = (person.center_x - image_width / 2.0) / float(image_width)
    if abs(center_error_ratio) > center_tolerance_ratio:
        if center_error_ratio < 0.0:
            reasons.append("person_left_of_sensor_cone")
        else:
            reasons.append("person_right_of_sensor_cone")

    return len(reasons) == 0, reasons


def gate_tilt_person(
    *,
    person: PersonBox | None,
    image_width: int,
    image_height: int,
    center_tolerance_ratio: float,
    edge_margin_px: float,
    role: str,
) -> tuple[bool, list[str]]:
    """Gate a split-tilt frame.

    Top tilt only needs a visible head point. Bottom tilt only needs a visible foot point.
    Both still need the person centered in the calibrated middle band.
    """
    if person is None:
        return False, ["no_person_detected"]

    reasons: list[str] = []
    center_error_ratio = (person.center_x - image_width / 2.0) / float(image_width)
    if abs(center_error_ratio) > center_tolerance_ratio:
        if center_error_ratio < 0.0:
            reasons.append("person_left_of_sensor_cone")
        else:
            reasons.append("person_right_of_sensor_cone")

    if role == "top" and person.top_y <= edge_margin_px:
        reasons.append("head_cut_off")
    if role == "bottom" and person.bottom_y >= image_height - edge_margin_px:
        reasons.append("feet_cut_off")

    return len(reasons) == 0, reasons


def guidance_from_reasons(reasons: list[str]) -> str:
    if "depth_not_on_person" in reasons or "depth_matches_background" in reasons or "depth_matches_nonhuman_object" in reasons:
        return "HUMAN_DETECTED_DEPTH_NOT_ON_PERSON"
    if "foreground_object_no_person" in reasons:
        return "OBJECT_DETECTED_NO_PERSON"
    if "no_person_detected" in reasons:
        return "NOTHING_DETECTED"
    if "person_too_small_or_far" in reasons:
        return "PERSON_DETECTED_MOVE_CLOSER"
    if "person_too_large_or_close" in reasons:
        return "PERSON_DETECTED_MOVE_BACK"
    if "person_left_of_sensor_cone" in reasons:
        return "PERSON_DETECTED_MOVE_RIGHT"
    if "person_right_of_sensor_cone" in reasons:
        return "PERSON_DETECTED_MOVE_LEFT"
    if "head_cut_off" in reasons:
        return "PERSON_DETECTED_HEAD_CUT_OFF"
    if "feet_cut_off" in reasons:
        return "PERSON_DETECTED_FEET_CUT_OFF"
    if "distance_too_far" in reasons:
        return "PERSON_DETECTED_MOVE_CLOSER"
    if "distance_too_close" in reasons:
        return "PERSON_DETECTED_MOVE_BACK"
    if "baseline_head_never_reached" in reasons or "baseline_pitch_too_large" in reasons:
        return "PERSON_DETECTED_MOVE_BACK"
    if "baseline_pitch_too_small" in reasons:
        return "PERSON_DETECTED_MOVE_CLOSER"
    if "baseline_unusable" in reasons:
        return "PERSON_DETECTED_NOT_READY"
    return "PERSON_DETECTED_NOT_READY"


def display_message_from_guidance(guidance: str, reasons: list[str]) -> str:
    if "depth_not_on_person" in reasons or "depth_matches_background" in reasons or "depth_matches_nonhuman_object" in reasons:
        return "Human detected, depth is hitting non-human object"
    if "distance_too_close" in reasons or "person_too_large_or_close" in reasons:
        return "Take one step back"
    if "distance_too_far" in reasons or "person_too_small_or_far" in reasons:
        return "Move closer"
    if "baseline_head_never_reached" in reasons or "baseline_pitch_too_large" in reasons:
        return "Move back"
    if "baseline_pitch_too_small" in reasons:
        return "Move closer"
    if "baseline_unusable" in reasons:
        return "Try again"
    if "person_left_of_sensor_cone" in reasons:
        return "Move right"
    if "person_right_of_sensor_cone" in reasons:
        return "Move left"
    if "head_cut_off" in reasons:
        return "Move back: head is cut off"
    if "feet_cut_off" in reasons:
        return "Move back: feet are cut off"
    if "foreground_object_no_person" in reasons:
        return "Object detected, no person"
    if "no_person_detected" in reasons:
        return "No person detected"
    if guidance == "HUMAN_LOCKED_SPLIT_TILT":
        return "Hold still"
    if guidance == "HUMAN_LOCKED":
        return "Hold still"
    return "Reposition"


def write_display_message(args: argparse.Namespace, message: str) -> str | None:
    if not args.display_message_output:
        return None
    output = Path(args.display_message_output)
    if not output.is_absolute():
        output = Path(args.output_dir) / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(message + "\n", encoding="utf-8")
    return str(output)


def gate_distance(distance_cm: float, *, min_cm: float, max_cm: float) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if distance_cm < min_cm:
        reasons.append("distance_too_close")
    if distance_cm > max_cm:
        reasons.append("distance_too_far")
    return len(reasons) == 0, reasons


def depth_sensor_to_camera_distance_cm(args: argparse.Namespace, sensor_distance_cm: float) -> float:
    """Convert HC-SR04 face-to-target distance to dog-camera lens-to-target distance."""
    sensor_distance_cm = max(0.0, float(sensor_distance_cm))
    behind_cm = max(0.0, float(args.depth_sensor_behind_camera_cm))
    above_cm = abs(float(args.depth_sensor_above_camera_cm))
    sensor_forward_cm = math.sqrt(max(0.0, sensor_distance_cm * sensor_distance_cm - above_cm * above_cm))
    return max(0.0, sensor_forward_cm - behind_cm)


def distance_looks_like_nonhuman_target(
    *,
    person: PersonBox,
    image_height: int,
    distance_cm: float,
    min_measure_distance_cm: float,
    background_distance_cm: float | None,
    background_match_cm: float,
    near_depth_visual_height_ratio: float,
) -> tuple[bool, list[str]]:
    """Detect when HC-SR04 is likely seeing a non-human target instead of the visible person."""
    reasons: list[str] = []
    if background_distance_cm is not None and abs(distance_cm - background_distance_cm) <= background_match_cm:
        reasons.append("depth_matches_background")

    if distance_cm < min_measure_distance_cm:
        height_ratio = person.height / float(image_height)
        person_is_visually_near = height_ratio >= near_depth_visual_height_ratio
        person_is_cut_off = person.top_y <= 5 or person.bottom_y >= image_height - 5
        if not person_is_visually_near and not person_is_cut_off:
            reasons.append("depth_not_on_person")

    return bool(reasons), reasons


def read_distance(args: argparse.Namespace) -> tuple[float, str]:
    if args.manual_distance_cm is not None:
        return float(args.manual_distance_cm), "manual"
    if not args.hcsr04:
        raise RuntimeError("Use --hcsr04 for the Pi sensor or --manual-distance-cm for a test.")
    sensor_distance_cm = read_hcsr04_distance_cm(
        trigger_pin=args.hcsr04_trigger_pin,
        echo_pin=args.hcsr04_echo_pin,
        samples=args.hcsr04_samples,
        sample_delay_sec=args.hcsr04_sample_delay_sec,
        max_distance_cm=args.hcsr04_max_distance_cm,
    )
    return depth_sensor_to_camera_distance_cm(args, sensor_distance_cm), "hcsr04"


def read_distance_samples(args: argparse.Namespace) -> tuple[float, str, list[float]]:
    if args.manual_distance_cm is not None:
        value = float(args.manual_distance_cm)
        return value, "manual", [value]
    if not args.hcsr04:
        raise RuntimeError("Use --hcsr04 for the Pi sensor or --manual-distance-cm for a test.")

    samples: list[float] = []
    for index in range(max(1, args.human_depth_bursts)):
        sensor_distance_cm = read_hcsr04_distance_cm(
            trigger_pin=args.hcsr04_trigger_pin,
            echo_pin=args.hcsr04_echo_pin,
            samples=args.hcsr04_samples,
            sample_delay_sec=args.hcsr04_sample_delay_sec,
            max_distance_cm=args.hcsr04_max_distance_cm,
        )
        samples.append(depth_sensor_to_camera_distance_cm(args, sensor_distance_cm))
        if index + 1 < max(1, args.human_depth_bursts):
            time.sleep(max(0.0, args.human_depth_burst_delay_sec))

    return float(statistics.median(samples)), "hcsr04", samples


def read_human_distance(
    args: argparse.Namespace,
    *,
    person: PersonBox,
    image_height: int,
) -> tuple[float, str, list[float], list[str]]:
    distance_cm, source, samples = read_distance_samples(args)
    if source == "manual":
        return distance_cm, source, samples, []

    candidates: list[float] = []
    rejected_reasons: list[str] = []
    for sample_cm in samples:
        reject, reasons = distance_looks_like_nonhuman_target(
            person=person,
            image_height=image_height,
            distance_cm=sample_cm,
            min_measure_distance_cm=args.min_measure_distance_cm,
            background_distance_cm=args.background_distance_cm,
            background_match_cm=args.background_distance_match_cm,
            near_depth_visual_height_ratio=args.near_depth_visual_height_ratio,
        )
        if reject:
            for reason in reasons:
                if reason not in rejected_reasons:
                    rejected_reasons.append(reason)
            continue
        candidates.append(sample_cm)

    if candidates:
        filtered_source = "hcsr04_filtered" if len(candidates) != len(samples) else source
        return float(statistics.median(candidates)), filtered_source, samples, []

    return distance_cm, "hcsr04_rejected", samples, rejected_reasons


def learn_background_distance_cm(args: argparse.Namespace) -> float | None:
    if not args.detect_foreground_no_person:
        return None
    if args.manual_distance_cm is not None:
        return float(args.manual_distance_cm)
    if not args.hcsr04:
        return None

    values: list[float] = []
    deadline = time.monotonic() + max(0.1, args.background_learn_sec)
    print(
        f"LEARNING_BACKGROUND keep wall/empty space in front of sensor for {args.background_learn_sec:.1f}s",
        flush=True,
    )
    while time.monotonic() < deadline:
        try:
            distance_cm, _source = read_distance(args)
        except RuntimeError:
            time.sleep(0.1)
            continue
        values.append(distance_cm)
        time.sleep(max(0.05, args.interval_sec))

    if not values:
        print("BACKGROUND_NOT_LEARNED object/no-person depth gate disabled", flush=True)
        return None
    values.sort()
    background_cm = values[len(values) // 2]
    print(f"BACKGROUND_LEARNED distance_cm={background_cm:.1f}", flush=True)
    return background_cm


def annotate_frame(
    image,
    *,
    detections: list[PersonBox],
    selected: PersonBox | None,
    accepted: bool,
    reasons: list[str],
    guidance: str,
    height_cm: float | None,
    center_tolerance_ratio: float,
    output: Path,
    baseline_y_px: float | None = None,
    extra_label: str | None = None,
) -> None:
    cv2, _np = require_cv2_numpy()
    image_height, image_width = image.shape[:2]
    left_gate = int(round(image_width * (0.5 - center_tolerance_ratio)))
    right_gate = int(round(image_width * (0.5 + center_tolerance_ratio)))
    cv2.line(image, (left_gate, 0), (left_gate, image_height), (0, 255, 255), 2)
    cv2.line(image, (right_gate, 0), (right_gate, image_height), (0, 255, 255), 2)
    if baseline_y_px is not None:
        y = int(round(baseline_y_px))
        if 0 <= y < image_height:
            cv2.line(image, (0, y), (image_width, y), (255, 255, 0), 2)
            cv2.putText(
                image,
                "33.5cm level",
                (12, min(image_height - 12, y + 28)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 255, 0),
                2,
            )

    for index, box in enumerate(detections):
        color = (0, 220, 0) if box is selected and accepted else (0, 0, 255)
        cv2.rectangle(image, (box.x, box.y), (box.x + box.width, box.y + box.height), color, 3)
        label = f"person {index} {box.score:.2f}"
        cv2.putText(image, label, (box.x, max(20, box.y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

    if accepted:
        text = "HUMAN LOCKED"
        if height_cm is not None:
            text += f" height={height_cm:.1f}cm"
        color = (0, 220, 0)
    else:
        text = f"{guidance}: " + ",".join(reasons)
        color = (0, 0, 255)
    if extra_label:
        text = f"{text} {extra_label}"

    cv2.rectangle(image, (0, 0), (image_width, 42), (0, 0, 0), -1)
    cv2.putText(image, text[:110], (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.75, color, 2)
    output.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output), image)


def write_three_image_preview(
    *,
    initial_annotated: Path,
    top_annotated: Path,
    bottom_annotated: Path,
    output: Path,
) -> str | None:
    cv2, _np = require_cv2_numpy()
    labels = [
        ("CENTER CHECK", initial_annotated),
        ("TOP TILT / HEAD", top_annotated),
        ("BOTTOM TILT / FEET", bottom_annotated),
    ]
    panels = []
    target_height = 360
    for label, path in labels:
        image = cv2.imread(str(path))
        if image is None:
            return None
        height, width = image.shape[:2]
        scale = target_height / float(height)
        resized = cv2.resize(image, (int(round(width * scale)), target_height))
        cv2.rectangle(resized, (0, 0), (resized.shape[1], 34), (0, 0, 0), -1)
        cv2.putText(resized, label, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        panels.append(resized)

    max_height = max(panel.shape[0] for panel in panels)
    normalized = []
    for panel in panels:
        if panel.shape[0] == max_height:
            normalized.append(panel)
            continue
        pad = max_height - panel.shape[0]
        normalized.append(cv2.copyMakeBorder(panel, 0, pad, 0, 0, cv2.BORDER_CONSTANT, value=(0, 0, 0)))

    preview = cv2.hconcat(normalized)
    output.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output), preview)
    return str(output)


def write_sweep_preview(*, annotated_images: list[Path], output: Path) -> str | None:
    cv2, _np = require_cv2_numpy()
    if not annotated_images:
        return None
    panels = []
    target_height = 260
    for path in annotated_images[:8]:
        image = cv2.imread(str(path))
        if image is None:
            continue
        height, width = image.shape[:2]
        scale = target_height / float(height)
        panels.append(cv2.resize(image, (int(round(width * scale)), target_height)))
    if not panels:
        return None
    preview = cv2.hconcat(panels)
    output.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output), preview)
    return str(output)


def estimate_neutral_baseline_geometry(
    *,
    person: PersonBox,
    image_width: int,
    image_height: int,
    distance_cm: float,
    camera_height_cm: float,
    calibration,
) -> dict[str, object]:
    foot_local_ray = vertical_ray_deg_from_pixel_calibration(
        x=person.center_x,
        y=person.bottom_y,
        image_width=image_width,
        image_height=image_height,
        calibration=calibration,
        camera_pitch_deg=0.0,
    )
    foot_local_ray_deg = float(foot_local_ray["ray_world_deg"])
    floor_ray_world_deg = math.degrees(math.atan2(-camera_height_cm, distance_cm))
    neutral_camera_pitch_deg = floor_ray_world_deg - foot_local_ray_deg
    baseline_local_ray_deg = -neutral_camera_pitch_deg
    baseline_pixel = pixel_y_for_vertical_ray_deg_calibration(
        local_ray_deg=baseline_local_ray_deg,
        image_width=image_width,
        image_height=image_height,
        calibration=calibration,
    )
    return {
        "camera_height_cm": camera_height_cm,
        "foot_local_ray_deg": foot_local_ray_deg,
        "floor_ray_world_deg": floor_ray_world_deg,
        "neutral_camera_pitch_deg": neutral_camera_pitch_deg,
        "baseline_local_ray_deg": baseline_local_ray_deg,
        "baseline_y_px": float(baseline_pixel["pixel_y"]),
        "baseline_pixel": baseline_pixel,
        "foot_ray": foot_local_ray,
    }


def capture_detect_person_frame(
    args: argparse.Namespace,
    *,
    frame_index: int,
    label: str,
    role: str,
    baseline_y_px: float | None = None,
    extra_label: str | None = None,
) -> dict[str, object]:
    cv2, _np = require_cv2_numpy()
    output_dir = Path(args.output_dir)
    image_path = output_dir / f"human_height_{frame_index:04d}_{label}.jpg"
    annotated_path = output_dir / f"human_height_{frame_index:04d}_{label}_annotated.jpg"

    capture_one_frame(rtsp_url=args.rtsp_url, output=image_path, jpeg_quality=args.jpeg_quality)
    image = cv2.imread(str(image_path))
    if image is None:
        raise RuntimeError(f"OpenCV could not read captured image: {image_path}")
    image_height, image_width = image.shape[:2]

    detections = detect_people_yolo(
        image_path,
        model_path=Path(args.yolo_model),
        confidence_threshold=args.yolo_confidence,
        nms_threshold=args.yolo_nms,
        image_size=args.yolo_image_size,
    )
    selected = choose_person(detections, args.person_index)
    accepted, reasons = gate_tilt_person(
        person=selected,
        image_width=image_width,
        image_height=image_height,
        center_tolerance_ratio=args.center_tolerance_ratio,
        edge_margin_px=args.edge_margin_px,
        role=role,
    )
    guidance = guidance_from_reasons(reasons)
    annotate_frame(
        image,
        detections=detections,
        selected=selected,
        accepted=accepted,
        reasons=reasons,
        guidance=guidance,
        height_cm=None,
        center_tolerance_ratio=args.center_tolerance_ratio,
        output=annotated_path,
        baseline_y_px=baseline_y_px,
        extra_label=extra_label,
    )
    return {
        "image": str(image_path),
        "annotated_image": str(annotated_path),
        "image_width": image_width,
        "image_height": image_height,
        "accepted": accepted,
        "reasons": reasons,
        "guidance": guidance,
        "selected_person": None if selected is None else asdict(selected),
        "detections": [asdict(detection) for detection in detections],
        "_selected": selected,
    }


async def connect_robot_motion(args: argparse.Namespace):
    try:
        import ff_sdk
        from ff_sdk import Config
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Split-tilt capture needs ff_sdk on the Pi. Use the Pi Python where ff_sdk is installed."
        ) from exc

    os.environ.setdefault("FF_SDK_D1_HOST", args.robot_host)
    os.environ.setdefault("FF_SDK_D1_VARIANT", args.robot_variant)
    return await ff_sdk.connect(args.robot_target, config=Config.from_env())


async def hold_pitch(sess, *, pitch_vel: float, seconds: float, hz: float) -> None:
    iterations = max(1, int(round(max(0.05, seconds) * max(1.0, hz))))
    delay = 1.0 / max(1.0, hz)
    for _ in range(iterations):
        await sess.motion.attitude_control(pitch_vel=pitch_vel)
        await asyncio.sleep(delay)


async def release_attitude(sess) -> None:
    await sess.motion.attitude_control()


def run_robot_pitch_step(
    args: argparse.Namespace,
    *,
    pitch_vel: float,
    stand_first: bool,
    seconds: float | None = None,
    stop_seconds: float | None = None,
    stand_wait_sec: float | None = None,
) -> dict[str, object] | None:
    helper = Path(args.robot_tilt_helper)
    cmd = [
        args.robot_python,
        str(helper),
        "--target",
        args.robot_target,
        "--host",
        args.robot_host,
        "--variant",
        args.robot_variant,
        "--pitch-vel",
        f"{pitch_vel:.6f}",
        "--seconds",
        f"{args.tilt_sweep_sec if seconds is None else seconds:.3f}",
        "--stop-seconds",
        f"{args.tilt_stop_sec if stop_seconds is None else stop_seconds:.3f}",
        "--hz",
        f"{args.tilt_hz:.3f}",
    ]
    if stand_first and args.tilt_stand_first:
        cmd.extend(["--stand-wait", f"{args.tilt_stand_wait_sec if stand_wait_sec is None else stand_wait_sec:.3f}"])
    else:
        cmd.append("--skip-stand")
    if args.codey_pitch:
        cmd.append("--codey")
        if args.codey_pitch_required:
            cmd.append("--codey-required")
        if args.codey_port:
            cmd.extend(["--codey-port", args.codey_port])
        cmd.extend(
            [
                "--codey-baud",
                str(args.codey_baud),
                "--codey-samples",
                str(args.codey_samples),
                "--codey-timeout-sec",
                f"{args.codey_timeout_sec:.3f}",
            ]
        )

    env = os.environ.copy()
    env["FF_SDK_D1_HOST"] = args.robot_host
    env["FF_SDK_D1_VARIANT"] = args.robot_variant
    if args.robot_ld_library_path:
        previous = env.get("LD_LIBRARY_PATH")
        env["LD_LIBRARY_PATH"] = (
            args.robot_ld_library_path if not previous else args.robot_ld_library_path + os.pathsep + previous
        )

    print("RUN_TILT_HELPER " + " ".join(cmd), flush=True)
    completed = subprocess.run(cmd, cwd=Path.cwd(), env=env, check=False, capture_output=True, text=True)
    if completed.stdout:
        print(completed.stdout, end="", flush=True)
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr, flush=True)
    completed.check_returncode()
    return parse_pitch_step_summary(completed.stdout)


def return_robot_to_standing(args: argparse.Namespace) -> dict[str, object] | None:
    if not args.return_stand_after_auto_tilt:
        return None
    print("RETURN_STAND_AFTER_AUTO_TILT", flush=True)
    return run_robot_pitch_step(
        args,
        pitch_vel=0.0,
        stand_first=True,
        seconds=0.05,
        stop_seconds=args.tilt_stop_sec,
        stand_wait_sec=args.tilt_return_stand_wait_sec,
    )


def parse_pitch_step_summary(output: str) -> dict[str, object] | None:
    for line in reversed(output.splitlines()):
        if not line.startswith("PITCH_STEP_SUMMARY "):
            continue
        try:
            return json.loads(line.split(" ", 1)[1])
        except json.JSONDecodeError:
            return None
    return None


def measured_pitch_increment_deg(tilt_report: dict[str, object] | None) -> float | None:
    if not isinstance(tilt_report, dict):
        return None
    value = tilt_report.get("abs_delta_deg")
    if value is None:
        return None
    value_f = float(value)
    if value_f <= 0.0:
        return None
    return value_f


def measured_absolute_pitch_deg(tilt_report: dict[str, object] | None, default: float) -> float:
    if not isinstance(tilt_report, dict):
        return default
    value = tilt_report.get("after_step_relative_deg")
    if value is None:
        return default
    return float(value)


async def capture_split_tilt_height(
    args: argparse.Namespace,
    *,
    frame_index: int,
    calibration,
    distance_cm: float,
    initial_annotated_path: Path,
) -> dict[str, object]:
    top_result: dict[str, object] | None = None
    bottom_result: dict[str, object] | None = None

    print(f"SPLIT_TILT_TOP pitch_vel={args.tilt_pitch_vel:.2f}", flush=True)
    top_tilt_report = run_robot_pitch_step(args, pitch_vel=abs(args.tilt_pitch_vel), stand_first=True)
    print(f"WAITING {args.tilt_settle_sec:.1f} SECONDS FOR STREAM SETTLE", flush=True)
    await asyncio.sleep(max(0.0, args.tilt_settle_sec))
    top_result = capture_detect_person_frame(args, frame_index=frame_index, label="top_tilt", role="top")

    print(f"SPLIT_TILT_BOTTOM pitch_vel={-abs(args.tilt_pitch_vel):.2f}", flush=True)
    bottom_tilt_report = run_robot_pitch_step(args, pitch_vel=-abs(args.tilt_pitch_vel), stand_first=False)
    print(f"WAITING {args.tilt_settle_sec:.1f} SECONDS FOR STREAM SETTLE", flush=True)
    await asyncio.sleep(max(0.0, args.tilt_settle_sec))
    bottom_result = capture_detect_person_frame(args, frame_index=frame_index, label="bottom_tilt", role="bottom")

    assert top_result is not None
    assert bottom_result is not None
    top_person = top_result.pop("_selected")
    bottom_person = bottom_result.pop("_selected")

    reasons: list[str] = []
    if not top_result["accepted"]:
        reasons.extend([f"top_{reason}" for reason in top_result["reasons"]])
    if not bottom_result["accepted"]:
        reasons.extend([f"bottom_{reason}" for reason in bottom_result["reasons"]])

    if reasons or top_person is None or bottom_person is None:
        return {
            "accepted": False,
            "reasons": reasons or ["split_tilt_person_not_detected"],
            "guidance": guidance_from_reasons([reason.replace("top_", "").replace("bottom_", "") for reason in reasons]),
            "top": top_result,
            "bottom": bottom_result,
            "height": None,
        }

    height_metrics = estimate_height_from_split_tilt_calibration(
        top_person=top_person,
        bottom_person=bottom_person,
        top_image_width=int(top_result["image_width"]),
        top_image_height=int(top_result["image_height"]),
        bottom_image_width=int(bottom_result["image_width"]),
        bottom_image_height=int(bottom_result["image_height"]),
        distance_cm=distance_cm,
        calibration=calibration,
        top_camera_pitch_deg=measured_absolute_pitch_deg(top_tilt_report, args.top_camera_pitch_deg),
        bottom_camera_pitch_deg=measured_absolute_pitch_deg(bottom_tilt_report, args.bottom_camera_pitch_deg),
    )
    return {
        "accepted": True,
        "reasons": [],
        "guidance": "HUMAN_LOCKED_SPLIT_TILT",
        "top": top_result,
        "bottom": bottom_result,
        "top_tilt_report": top_tilt_report,
        "bottom_tilt_report": bottom_tilt_report,
        "three_image_preview": write_three_image_preview(
            initial_annotated=initial_annotated_path,
            top_annotated=Path(str(top_result["annotated_image"])),
            bottom_annotated=Path(str(bottom_result["annotated_image"])),
            output=Path(args.output_dir) / f"human_height_{frame_index:04d}_split_tilt_preview.jpg",
        ),
        "height": height_metrics,
    }


async def capture_baseline_sweep_height(
    args: argparse.Namespace,
    *,
    frame_index: int,
    calibration,
    distance_cm: float,
    initial_person: PersonBox,
    initial_image_width: int,
    initial_image_height: int,
    initial_annotated_path: Path,
) -> dict[str, object]:
    baseline = estimate_neutral_baseline_geometry(
        person=initial_person,
        image_width=initial_image_width,
        image_height=initial_image_height,
        distance_cm=distance_cm,
        camera_height_cm=args.camera_height_cm,
        calibration=calibration,
    )
    baseline_y = float(baseline["baseline_y_px"])
    if baseline_y < 0.0 or baseline_y >= initial_image_height:
        return {
            "accepted": False,
            "reasons": ["baseline_unusable"],
            "guidance": guidance_from_reasons(["baseline_unusable"]),
            "baseline": baseline,
            "steps": [],
            "height": None,
        }

    step_pitch_deg = abs(args.baseline_pitch_vel) * args.baseline_pitch_step_sec * 180.0 / math.pi
    max_steps = max(1, int(math.ceil(args.baseline_max_up_pitch_deg / max(0.1, step_pitch_deg))))
    max_steps = min(max_steps, args.baseline_max_steps)

    previous_pitch_deg = 0.0
    cumulative_pitch_deg = 0.0
    previous_delta_px = initial_person.top_y - baseline_y
    steps: list[dict[str, object]] = [
        {
            "step": 0,
            "pitch_deg": 0.0,
            "head_y_px": initial_person.top_y,
            "baseline_y_px": baseline_y,
            "head_minus_baseline_px": previous_delta_px,
            "annotated_image": str(initial_annotated_path),
        }
    ]
    annotated_images = [initial_annotated_path]

    if previous_delta_px >= 0.0:
        return {
            "accepted": False,
            "reasons": ["baseline_pitch_too_small"],
            "guidance": guidance_from_reasons(["baseline_pitch_too_small"]),
            "baseline": baseline,
            "steps": steps,
            "height": None,
        }

    print(
        f"BASELINE_SWEEP baseline_y={baseline_y:.1f}px step={step_pitch_deg:.2f}deg "
        f"max={args.baseline_max_up_pitch_deg:.1f}deg",
        flush=True,
    )
    for step in range(1, max_steps + 1):
        tilt_report = run_robot_pitch_step(
            args,
            pitch_vel=abs(args.baseline_pitch_vel),
            stand_first=(step == 1),
            seconds=args.baseline_pitch_step_sec,
            stop_seconds=args.baseline_pitch_stop_sec,
        )
        await asyncio.sleep(max(0.0, args.tilt_settle_sec))
        pitch_increment_deg = measured_pitch_increment_deg(tilt_report)
        if pitch_increment_deg is None:
            pitch_increment_deg = step_pitch_deg
            pitch_source = "estimated_from_velocity"
        else:
            pitch_source = "codey_measured"
        cumulative_pitch_deg = min(cumulative_pitch_deg + pitch_increment_deg, args.baseline_max_up_pitch_deg)
        pitch_deg = cumulative_pitch_deg
        capture = capture_detect_person_frame(
            args,
            frame_index=frame_index,
            label=f"baseline_sweep_{step:02d}",
            role="top",
            baseline_y_px=baseline_y,
            extra_label=f"pitch~{pitch_deg:.1f}deg",
        )
        selected = capture.pop("_selected")
        annotated_images.append(Path(str(capture["annotated_image"])))

        if selected is None:
            steps.append(
                {
                    "step": step,
                    "pitch_deg": pitch_deg,
                    "head_y_px": None,
                    "baseline_y_px": baseline_y,
                    "head_minus_baseline_px": None,
                    "accepted": False,
                    "reasons": ["no_person_detected"],
                    "pitch_source": pitch_source,
                    "tilt_report": tilt_report,
                    "capture": capture,
                }
            )
            continue

        current_delta_px = selected.top_y - baseline_y
        steps.append(
            {
                "step": step,
                "pitch_deg": pitch_deg,
                "head_y_px": selected.top_y,
                "baseline_y_px": baseline_y,
                "head_minus_baseline_px": current_delta_px,
                "accepted": capture["accepted"],
                "reasons": capture["reasons"],
                "pitch_source": pitch_source,
                "tilt_report": tilt_report,
                "capture": capture,
            }
        )

        if current_delta_px >= 0.0 and previous_delta_px < 0.0:
            denom = current_delta_px - previous_delta_px
            fraction = 1.0 if abs(denom) < 1e-6 else (0.0 - previous_delta_px) / denom
            fraction = max(0.0, min(1.0, fraction))
            crossing_pitch_deg = previous_pitch_deg + fraction * (pitch_deg - previous_pitch_deg)
            if crossing_pitch_deg < args.baseline_min_usable_pitch_deg:
                return {
                    "accepted": False,
                    "reasons": ["baseline_pitch_too_small"],
                    "guidance": guidance_from_reasons(["baseline_pitch_too_small"]),
                    "baseline": baseline,
                    "steps": steps,
                    "sweep_preview": write_sweep_preview(
                        annotated_images=annotated_images,
                        output=Path(args.output_dir) / f"human_height_{frame_index:04d}_baseline_sweep_preview.jpg",
                    ),
                    "height": None,
                }
            if crossing_pitch_deg > args.baseline_max_usable_pitch_deg:
                return {
                    "accepted": False,
                    "reasons": ["baseline_pitch_too_large"],
                    "guidance": guidance_from_reasons(["baseline_pitch_too_large"]),
                    "baseline": baseline,
                    "steps": steps,
                    "sweep_preview": write_sweep_preview(
                        annotated_images=annotated_images,
                        output=Path(args.output_dir) / f"human_height_{frame_index:04d}_baseline_sweep_preview.jpg",
                    ),
                    "height": None,
                }

            person_height_cm = args.camera_height_cm + distance_cm * math.tan(math.radians(crossing_pitch_deg))
            height_metrics = {
                "height_method": "baseline_pitch_sweep",
                "camera_height_cm": args.camera_height_cm,
                "distance_cm": distance_cm,
                "crossing_pitch_deg": crossing_pitch_deg,
                "pitch_step_deg": step_pitch_deg,
                "pitch_source": "codey_measured" if args.codey_pitch else "estimated_from_velocity",
                "crossing_interpolation_fraction": fraction,
                "person_height_cm": person_height_cm,
                "person_height_in": person_height_cm / 2.54,
                "baseline": baseline,
            }
            return {
                "accepted": True,
                "reasons": [],
                "guidance": "HUMAN_LOCKED_BASELINE_SWEEP",
                "baseline": baseline,
                "steps": steps,
                "sweep_preview": write_sweep_preview(
                    annotated_images=annotated_images,
                    output=Path(args.output_dir) / f"human_height_{frame_index:04d}_baseline_sweep_preview.jpg",
                ),
                "height": height_metrics,
            }

        previous_pitch_deg = pitch_deg
        previous_delta_px = current_delta_px

    return {
        "accepted": False,
        "reasons": ["baseline_head_never_reached"],
        "guidance": guidance_from_reasons(["baseline_head_never_reached"]),
        "baseline": baseline,
        "steps": steps,
        "sweep_preview": write_sweep_preview(
            annotated_images=annotated_images,
            output=Path(args.output_dir) / f"human_height_{frame_index:04d}_baseline_sweep_preview.jpg",
        ),
        "height": None,
    }


def process_once(args: argparse.Namespace, *, frame_index: int, calibration) -> dict[str, object]:
    cv2, _np = require_cv2_numpy()
    output_dir = Path(args.output_dir)
    image_path = output_dir / f"human_height_{frame_index:04d}.jpg"
    annotated_path = output_dir / f"human_height_{frame_index:04d}_annotated.jpg"

    capture_one_frame(rtsp_url=args.rtsp_url, output=image_path, jpeg_quality=args.jpeg_quality)
    image = cv2.imread(str(image_path))
    if image is None:
        raise RuntimeError(f"OpenCV could not read captured image: {image_path}")
    image_height, image_width = image.shape[:2]

    detections = detect_people_yolo(
        image_path,
        model_path=Path(args.yolo_model),
        confidence_threshold=args.yolo_confidence,
        nms_threshold=args.yolo_nms,
        image_size=args.yolo_image_size,
    )
    selected = choose_person(detections, args.person_index)
    accepted, reasons = gate_person(
        person=selected,
        image_width=image_width,
        image_height=image_height,
        center_tolerance_ratio=args.center_tolerance_ratio,
        edge_margin_px=args.edge_margin_px,
        min_height_ratio=args.min_person_height_ratio,
        max_height_ratio=args.max_person_height_ratio,
    )

    distance_cm = None
    distance_source = None
    height_metrics = None
    split_tilt_result = None
    baseline_sweep_result = None
    baseline_y_for_annotation = None
    guidance = guidance_from_reasons(reasons)
    distance_samples_cm: list[float] | None = None
    human_depth_reasons: list[str] = []
    auto_tilt_mode = args.auto_tilt
    if args.baseline_sweep:
        auto_tilt_mode = "baseline"
    if args.split_tilt:
        auto_tilt_mode = "split"

    if selected is not None and (args.hcsr04 or args.manual_distance_cm is not None):
        distance_cm, distance_source, distance_samples_cm, human_depth_reasons = read_human_distance(
            args,
            person=selected,
            image_height=image_height,
        )

    if selected is None and args.detect_foreground_no_person and args.background_distance_cm is not None:
        distance_cm, distance_source = read_distance(args)
        foreground_trigger_cm = args.background_distance_cm - args.foreground_threshold_cm
        if distance_cm <= foreground_trigger_cm:
            reasons = ["foreground_object_no_person"]
            guidance = guidance_from_reasons(reasons)
        else:
            reasons = ["no_person_detected"]
            guidance = guidance_from_reasons(reasons)

    if accepted and selected is not None:
        if distance_cm is None:
            distance_cm, distance_source, distance_samples_cm, human_depth_reasons = read_human_distance(
                args,
                person=selected,
                image_height=image_height,
            )
        distance_ok, distance_reasons = gate_distance(
            distance_cm,
            min_cm=args.min_measure_distance_cm,
            max_cm=args.max_measure_distance_cm,
        )
        if human_depth_reasons:
            accepted = False
            reasons = human_depth_reasons + distance_reasons
            guidance = guidance_from_reasons(reasons)
        elif not distance_ok:
            accepted = False
            depth_not_person, depth_reasons = distance_looks_like_nonhuman_target(
                person=selected,
                image_height=image_height,
                distance_cm=distance_cm,
                min_measure_distance_cm=args.min_measure_distance_cm,
                background_distance_cm=args.background_distance_cm,
                background_match_cm=args.background_distance_match_cm,
                near_depth_visual_height_ratio=args.near_depth_visual_height_ratio,
            )
            if depth_not_person:
                reasons = depth_reasons + distance_reasons
            else:
                reasons = distance_reasons
            guidance = guidance_from_reasons(reasons)
        else:
            if auto_tilt_mode == "baseline":
                baseline_sweep_result = asyncio.run(
                    capture_baseline_sweep_height(
                        args,
                        frame_index=frame_index,
                        calibration=calibration,
                        distance_cm=distance_cm,
                        initial_person=selected,
                        initial_image_width=image_width,
                        initial_image_height=image_height,
                        initial_annotated_path=annotated_path,
                    )
                )
                baseline_sweep_result["return_stand_report"] = return_robot_to_standing(args)
                baseline = baseline_sweep_result.get("baseline") if isinstance(baseline_sweep_result, dict) else None
                if isinstance(baseline, dict):
                    baseline_y_for_annotation = float(baseline["baseline_y_px"])
                if baseline_sweep_result["accepted"]:
                    guidance = "HUMAN_LOCKED_BASELINE_SWEEP"
                    height_metrics = baseline_sweep_result["height"]
                else:
                    accepted = False
                    reasons = list(baseline_sweep_result["reasons"])
                    guidance = baseline_sweep_result["guidance"]
            elif auto_tilt_mode == "split":
                split_tilt_result = asyncio.run(
                    capture_split_tilt_height(
                        args,
                        frame_index=frame_index,
                        calibration=calibration,
                        distance_cm=distance_cm,
                        initial_annotated_path=annotated_path,
                    )
                )
                split_tilt_result["return_stand_report"] = return_robot_to_standing(args)
                if split_tilt_result["accepted"]:
                    guidance = "HUMAN_LOCKED_SPLIT_TILT"
                    height_metrics = split_tilt_result["height"]
                else:
                    accepted = False
                    reasons = list(split_tilt_result["reasons"])
                    guidance = split_tilt_result["guidance"]
            else:
                guidance = "HUMAN_LOCKED"
                height_metrics = estimate_height_from_box_calibration(
                    person=selected,
                    image_width=image_width,
                    image_height=image_height,
                    distance_cm=distance_cm,
                    calibration=calibration,
                    camera_pitch_deg=args.camera_pitch_deg,
                )

    annotate_frame(
        image,
        detections=detections,
        selected=selected,
        accepted=accepted,
        reasons=reasons,
        guidance=guidance,
        height_cm=None if height_metrics is None else float(height_metrics["person_height_cm"]),
        center_tolerance_ratio=args.center_tolerance_ratio,
        output=annotated_path,
        baseline_y_px=baseline_y_for_annotation,
    )

    result: dict[str, object] = {
        "frame_index": frame_index,
        "image": str(image_path),
        "annotated_image": str(annotated_path),
        "image_width": image_width,
        "image_height": image_height,
        "human_gate_ok": accepted,
        "person_detected": selected is not None,
        "human_distance_cm": distance_cm if selected is not None else None,
        "reasons": reasons,
        "guidance": guidance,
        "distance_used": height_metrics is not None,
        "distance_cm": distance_cm,
        "distance_samples_cm": distance_samples_cm,
        "distance_source": distance_source,
        "background_distance_cm": args.background_distance_cm,
        "depth_sensor_behind_camera_cm": args.depth_sensor_behind_camera_cm,
        "depth_sensor_above_camera_cm": args.depth_sensor_above_camera_cm,
        "auto_tilt": auto_tilt_mode,
        "selected_person": None if selected is None else asdict(selected),
        "detections": [asdict(detection) for detection in detections],
        "camera_calibration": args.camera_calibration,
        "camera_pitch_deg": args.camera_pitch_deg,
        "display_message": display_message_from_guidance(guidance, reasons),
        "split_tilt": split_tilt_result,
        "baseline_sweep": baseline_sweep_result,
        "height": height_metrics,
    }
    result["display_message_path"] = write_display_message(args, str(result["display_message"]))
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rtsp-url", default=DEFAULT_RTSP_URL)
    parser.add_argument("--output-dir", default="human_height_runs/latest")
    parser.add_argument(
        "--display-message-output",
        default="display_message.txt",
        help="Writes the latest screen prompt here, relative to --output-dir unless absolute. Use empty string to disable.",
    )
    parser.add_argument("--jpeg-quality", type=int, default=92)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval-sec", type=float, default=0.5)
    parser.add_argument("--max-frames", type=int, default=0, help="0 means forever unless --once is used.")

    parser.add_argument("--camera-calibration", default="calibrations/charuco_camera_calibration_refined.json")
    parser.add_argument("--camera-pitch-deg", type=float, default=0.0)

    parser.add_argument("--hcsr04", action="store_true")
    parser.add_argument("--manual-distance-cm", type=float, default=None)
    parser.add_argument("--hcsr04-trigger-pin", type=int, default=DEFAULT_HCSR04_TRIGGER_PIN)
    parser.add_argument("--hcsr04-echo-pin", type=int, default=DEFAULT_HCSR04_ECHO_PIN)
    parser.add_argument("--hcsr04-samples", type=int, default=7)
    parser.add_argument("--hcsr04-sample-delay-sec", type=float, default=0.04)
    parser.add_argument("--hcsr04-max-distance-cm", type=float, default=400.0)
    parser.add_argument(
        "--depth-sensor-behind-camera-cm",
        type=float,
        default=0.0,
        help=(
            "Positive distance from the camera lens back to the HC-SR04 face. "
            "The script subtracts this after correcting the HC-SR04 range for vertical offset."
        ),
    )
    parser.add_argument(
        "--depth-sensor-above-camera-cm",
        type=float,
        default=0.0,
        help=(
            "Positive distance from the camera lens up to the HC-SR04 face. "
            "Used with --depth-sensor-behind-camera-cm to convert sensor range to camera range."
        ),
    )
    parser.add_argument(
        "--human-depth-bursts",
        type=int,
        default=3,
        help="When a person is visible, take this many independent HC-SR04 reads and reject non-human/background hits.",
    )
    parser.add_argument(
        "--human-depth-burst-delay-sec",
        type=float,
        default=0.08,
        help="Delay between independent human-depth reads.",
    )
    parser.add_argument(
        "--detect-foreground-no-person",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="When no person is detected, use the learned background distance to report OBJECT_DETECTED_NO_PERSON.",
    )
    parser.add_argument(
        "--background-distance-cm",
        type=float,
        default=None,
        help="Known empty-wall/background distance. If omitted, the script learns it at startup.",
    )
    parser.add_argument(
        "--background-learn-sec",
        type=float,
        default=3.0,
        help="Seconds to learn empty wall/background distance at startup.",
    )
    parser.add_argument(
        "--foreground-threshold-cm",
        type=float,
        default=12.0,
        help="No-person object threshold: object must be this much closer than the background.",
    )
    parser.add_argument(
        "--background-distance-match-cm",
        type=float,
        default=15.0,
        help="When a person is visible, treat a depth reading this close to the learned wall/background as not on the person.",
    )
    parser.add_argument(
        "--near-depth-visual-height-ratio",
        type=float,
        default=0.85,
        help="If depth says very close but the person fills less than this image height ratio, ignore that depth as not on the person.",
    )
    parser.add_argument(
        "--min-measure-distance-cm",
        type=float,
        default=80.0,
        help="If the person is closer than this camera-corrected distance, do not estimate height.",
    )
    parser.add_argument(
        "--max-measure-distance-cm",
        type=float,
        default=380.0,
        help="If the person is farther than this camera-corrected distance, ask them to move closer.",
    )
    parser.add_argument(
        "--baseline-sweep",
        action="store_true",
        help=(
            "Estimate height by finding the 33.5 cm camera-height baseline row, then tilting up "
            "incrementally until the person's head crosses that row."
        ),
    )
    parser.add_argument(
        "--auto-tilt",
        choices=["none", "baseline", "split"],
        default="baseline",
        help=(
            "Automatic robot tilt mode after a centered person and usable depth are found. "
            "baseline is the current preferred height method."
        ),
    )
    parser.add_argument("--camera-height-cm", type=float, default=33.5)
    parser.add_argument("--baseline-pitch-vel", type=float, default=0.20)
    parser.add_argument("--baseline-pitch-step-sec", type=float, default=0.30)
    parser.add_argument("--baseline-pitch-stop-sec", type=float, default=0.15)
    parser.add_argument("--baseline-max-up-pitch-deg", type=float, default=25.0)
    parser.add_argument("--baseline-max-steps", type=int, default=14)
    parser.add_argument(
        "--baseline-min-usable-pitch-deg",
        type=float,
        default=8.0,
        help="If the head reaches the baseline with less pitch than this, the angle is too small/noisy.",
    )
    parser.add_argument(
        "--baseline-max-usable-pitch-deg",
        type=float,
        default=24.5,
        help="If the head needs more pitch than this, the person should move farther back.",
    )
    parser.add_argument(
        "--split-tilt",
        action="store_true",
        help="After the person is centered and distance-gated, capture top/bottom tilt frames and estimate height from both.",
    )
    parser.add_argument("--robot-python", default="/home/agent-tech/python3.10/bin/python3.10")
    parser.add_argument("--robot-ld-library-path", default="/home/agent-tech/python3.10/lib")
    parser.add_argument("--robot-tilt-helper", default="scripts/attitude_pitch_step.py")
    parser.add_argument("--robot-target", default="D1-XG03")
    parser.add_argument("--robot-host", default="192.168.234.1")
    parser.add_argument("--robot-variant", default="zsl-1")
    parser.add_argument(
        "--tilt-stand-first",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Call stand() before moving the pitch axis for split-tilt capture.",
    )
    parser.add_argument("--tilt-stand-wait-sec", type=float, default=10.0)
    parser.add_argument("--tilt-pitch-vel", type=float, default=0.35)
    parser.add_argument("--tilt-sweep-sec", type=float, default=3.0)
    parser.add_argument("--tilt-stop-sec", type=float, default=0.8)
    parser.add_argument(
        "--return-stand-after-auto-tilt",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "After an automatic tilt capture/sweep, command stand again. Off by default because "
            "this robot backend can drop into damping after SDK cleanup/reset paths."
        ),
    )
    parser.add_argument("--tilt-return-stand-wait-sec", type=float, default=4.0)
    parser.add_argument(
        "--tilt-settle-sec",
        type=float,
        default=2.0,
        help="Pause after each tilt move before taking the RTSP image; increase this if the stream lags.",
    )
    parser.add_argument("--tilt-hz", type=float, default=20.0)
    parser.add_argument("--top-camera-pitch-deg", type=float, default=18.0)
    parser.add_argument("--bottom-camera-pitch-deg", type=float, default=-19.0)
    parser.add_argument("--codey-pitch", action="store_true", help="Use Codey Rocky USB pitch readings during robot tilt.")
    parser.add_argument("--codey-pitch-required", action="store_true", help="Fail if Codey pitch cannot be read.")
    parser.add_argument("--codey-port", default="", help="Usually /dev/ttyUSB0 or /dev/ttyACM0. Empty auto-detects.")
    parser.add_argument("--codey-baud", type=int, default=115200)
    parser.add_argument("--codey-samples", type=int, default=3)
    parser.add_argument("--codey-timeout-sec", type=float, default=5.0)

    parser.add_argument("--yolo-model", default=DEFAULT_MODEL)
    parser.add_argument("--yolo-confidence", type=float, default=0.35)
    parser.add_argument("--yolo-nms", type=float, default=0.45)
    parser.add_argument("--yolo-image-size", type=int, default=640)
    parser.add_argument("--person-index", type=int, default=0)

    parser.add_argument(
        "--center-tolerance-ratio",
        type=float,
        default=0.16,
        help="Only use distance when the person center is inside this middle image band.",
    )
    parser.add_argument("--edge-margin-px", type=float, default=24.0)
    parser.add_argument("--min-person-height-ratio", type=float, default=0.25)
    parser.add_argument("--max-person-height-ratio", type=float, default=0.95)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    Path(args.output_dir).mkdir(parents=True, exist_ok=True)
    calibration = load_camera_calibration(args.camera_calibration)
    if args.background_distance_cm is None:
        args.background_distance_cm = learn_background_distance_cm(args)
    summary_path = Path(args.output_dir) / "human_height_results.jsonl"

    frame_index = 1
    while True:
        try:
            result = process_once(args, frame_index=frame_index, calibration=calibration)
        except RuntimeError as exc:
            message = str(exc)
            if "robot camera stream" not in message and "read a frame" not in message:
                raise
            print(f"CAMERA_STREAM_UNAVAILABLE reason={message}", flush=True)
            if args.once:
                break
            if args.max_frames and frame_index >= args.max_frames:
                break
            frame_index += 1
            time.sleep(max(0.0, args.interval_sec))
            continue

        with summary_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(result) + "\n")

        if result["human_gate_ok"]:
            height = result["height"] or {}
            split_tilt = result.get("split_tilt") or {}
            baseline_sweep = result.get("baseline_sweep") or {}
            top_image = ""
            bottom_image = ""
            sweep_image = ""
            if isinstance(split_tilt, dict) and split_tilt.get("accepted"):
                top = split_tilt.get("top") or {}
                bottom = split_tilt.get("bottom") or {}
                if isinstance(top, dict):
                    top_image = f" top_image={top.get('annotated_image', '')}"
                if isinstance(bottom, dict):
                    bottom_image = f" bottom_image={bottom.get('annotated_image', '')}"
                preview_image = f" preview_image={split_tilt.get('three_image_preview', '')}"
            elif isinstance(baseline_sweep, dict) and baseline_sweep.get("accepted"):
                preview_image = f" preview_image={baseline_sweep.get('sweep_preview', '')}"
                sweep_image = f" crossing_pitch_deg={height.get('crossing_pitch_deg', 0.0):.2f}"
            else:
                preview_image = ""
            print(
                f"{result['guidance']} "
                f"distance_cm={result['distance_cm']:.1f} "
                f"height_cm={height.get('person_height_cm', 0.0):.1f} "
                f"height_in={height.get('person_height_in', 0.0):.1f} "
                f"display='{result['display_message']}' "
                f"image={result['annotated_image']}"
                f"{top_image}"
                f"{bottom_image}"
                f"{sweep_image}"
                f"{preview_image}",
                flush=True,
            )
        else:
            human_distance = result.get("human_distance_cm")
            if result.get("person_detected"):
                detection_status = "HUMAN_DETECTED"
                distance_text = (
                    f" human_distance_cm={float(human_distance):.1f}"
                    if human_distance is not None
                    else " human_distance_cm=none"
                )
            else:
                detection_status = "NO_HUMAN"
                distance_text = ""
            print(
                f"{detection_status} "
                f"{result['guidance']} "
                f"reason={','.join(result['reasons'])} "
                f"detections={len(result['detections'])} "
                f"distance_cm={result['distance_cm'] if result['distance_cm'] is not None else 'none'} "
                f"{distance_text} "
                f"display='{result['display_message']}' "
                f"image={result['annotated_image']}",
                flush=True,
            )

        if args.once:
            break
        if args.max_frames and frame_index >= args.max_frames:
            break
        frame_index += 1
        time.sleep(max(0.0, args.interval_sec))


if __name__ == "__main__":
    main()
