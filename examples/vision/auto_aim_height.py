"""Auto-aim the Aegis/D1 robot for height measurement.

Run this on the Raspberry Pi. The Pi reads the HC-SR04 depth sensor, captures
the robot camera stream, detects the person with YOLO, decides how the robot
should move/aim, and optionally sends small commands to the robot.

Safety-first default: this script only prints decisions. It will not move the
robot unless --enable-motion is provided. Pitch is disabled unless
--enable-pitch is also provided.

Flow:

    Pi GPIO depth + robot camera frame -> decision -> optional robot command

Developer tilt notes:
    motion.attitude_control pitch_vel is rad/s. Negative pitch_vel lowers the head/camera
    in the current D1 joystick mapping.
    attitude_control is D1/quadruped-only.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import time
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path

from height_calculator import (
    DEFAULT_HCSR04_ECHO_PIN,
    DEFAULT_HCSR04_TRIGGER_PIN,
    DEFAULT_MODEL,
    DEFAULT_RTSP_URL,
    PersonBox,
    capture_one_frame,
    detect_people_yolo,
    estimate_height_from_box_fov,
    read_hcsr04_distance_cm,
)


@dataclass(frozen=True)
class AimDecision:
    action: str
    reason: str
    vx: float = 0.0
    vy: float = 0.0
    yaw: float = 0.0
    pitch_vel: float = 0.0

    @property
    def has_body_motion(self) -> bool:
        return any(abs(value) > 0.0 for value in (self.vx, self.vy, self.yaw))

    @property
    def has_pitch_motion(self) -> bool:
        return abs(self.pitch_vel) > 0.0


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def jsonable(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if is_dataclass(value) and not isinstance(value, type):
        return jsonable(asdict(value))
    return repr(value)


def choose_aim_decision(
    *,
    person: PersonBox | None,
    image_width: int,
    image_height: int,
    distance_cm: float,
    target_distance_cm: float,
    distance_tolerance_cm: float,
    center_tolerance_ratio: float,
    vertical_tolerance_ratio: float,
    edge_margin_px: float,
    forward_speed: float,
    back_speed: float,
    yaw_speed: float,
    pitch_speed: float,
) -> AimDecision:
    if person is None:
        return AimDecision(
            action="scan_left",
            reason="no_person_detected",
            yaw=abs(yaw_speed),
        )

    if person.top_y <= edge_margin_px:
        return AimDecision(
            action="back_up",
            reason="head_cut_off",
            vx=-abs(back_speed),
        )
    if person.bottom_y >= image_height - edge_margin_px:
        return AimDecision(
            action="back_up",
            reason="feet_cut_off",
            vx=-abs(back_speed),
        )

    if distance_cm < target_distance_cm - distance_tolerance_cm:
        return AimDecision(
            action="back_up",
            reason="too_close_by_depth",
            vx=-abs(back_speed),
        )
    if distance_cm > target_distance_cm + distance_tolerance_cm:
        return AimDecision(
            action="move_forward",
            reason="too_far_by_depth",
            vx=abs(forward_speed),
        )

    horizontal_error = (person.center_x - (image_width / 2.0)) / float(image_width)
    if horizontal_error < -center_tolerance_ratio:
        return AimDecision(
            action="yaw_left",
            reason="person_left_of_center",
            yaw=abs(yaw_speed),
        )
    if horizontal_error > center_tolerance_ratio:
        return AimDecision(
            action="yaw_right",
            reason="person_right_of_center",
            yaw=-abs(yaw_speed),
        )

    person_center_y = person.y + person.height / 2.0
    vertical_error = (person_center_y - (image_height / 2.0)) / float(image_height)
    if vertical_error > vertical_tolerance_ratio:
        return AimDecision(
            action="pitch_down",
            reason="person_low_in_image",
            pitch_vel=-abs(pitch_speed),
        )
    if vertical_error < -vertical_tolerance_ratio:
        return AimDecision(
            action="pitch_up",
            reason="person_high_in_image",
            pitch_vel=abs(pitch_speed),
        )

    return AimDecision(action="hold", reason="person_centered_and_distance_ok")


async def stream_move(motion, *, vx: float, vy: float, yaw: float, seconds: float):
    end = time.monotonic() + max(0.0, seconds)
    last_ret = None
    while time.monotonic() < end:
        last_ret = await motion.cmd_vel(linear=vx, lateral=vy, angular=yaw)
        await asyncio.sleep(0.05)
    stop_end = time.monotonic() + 0.4
    while time.monotonic() < stop_end:
        last_ret = await motion.stop()
        await asyncio.sleep(0.05)
    return last_ret


async def stream_pitch(motion, *, pitch_vel: float, seconds: float):
    attitude_control = getattr(motion, "attitude_control", None)
    if attitude_control is None:
        raise RuntimeError("Robot backend does not expose attitude_control() (D1 quadruped only).")

    end = time.monotonic() + max(0.0, seconds)
    last_ret = None
    while time.monotonic() < end:
        last_ret = await attitude_control(pitch_vel=pitch_vel)
        await asyncio.sleep(0.05)
    stop_end = time.monotonic() + 0.4
    while time.monotonic() < stop_end:
        last_ret = await attitude_control()
        await asyncio.sleep(0.05)
    return last_ret


async def connect_robot(args: argparse.Namespace):
    try:
        import ff_sdk
        from ff_sdk import Config
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Robot auto-aim needs ff_sdk installed on this Pi/Linux environment."
        ) from exc

    os.environ["FF_SDK_D1_HOST"] = args.host
    os.environ["FF_SDK_D1_VARIANT"] = args.variant
    return await ff_sdk.connect(args.target, config=Config.from_env())


def read_distance(args: argparse.Namespace) -> float:
    return read_hcsr04_distance_cm(
        trigger_pin=args.hcsr04_trigger_pin,
        echo_pin=args.hcsr04_echo_pin,
        samples=args.hcsr04_samples,
        sample_delay_sec=args.hcsr04_sample_delay_sec,
        max_distance_cm=args.hcsr04_max_distance_cm,
    )


def capture_and_detect(args: argparse.Namespace, *, step: int) -> tuple[Path, list[PersonBox], tuple[int, int]]:
    image_path = Path(args.output_dir) / f"auto_aim_{step:02d}.jpg"
    capture_one_frame(rtsp_url=args.rtsp_url, output=image_path, jpeg_quality=args.jpeg_quality)

    try:
        import cv2
    except ModuleNotFoundError as exc:
        raise RuntimeError("OpenCV is required. Install requirements-vision.txt first.") from exc

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
    return image_path, detections, (image_width, image_height)


def maybe_estimate_height(
    args: argparse.Namespace,
    *,
    person: PersonBox | None,
    image_height: int,
    distance_cm: float,
) -> dict[str, float] | None:
    if person is None or not args.estimate_height:
        return None
    return estimate_height_from_box_fov(
        person=person,
        image_height=image_height,
        distance_cm=distance_cm,
        vertical_fov_deg=args.vertical_fov_deg,
        camera_pitch_deg=args.camera_pitch_deg,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default=os.environ.get("FF_SDK_TARGET", "D1-XG03"))
    parser.add_argument("--host", default="192.168.234.1")
    parser.add_argument("--variant", default="zsl-1")
    parser.add_argument("--local-port", type=int, default=43988)
    parser.add_argument("--rtsp-url", default=DEFAULT_RTSP_URL)
    parser.add_argument("--output-dir", default="auto_aim_runs/latest")
    parser.add_argument("--jpeg-quality", type=int, default=92)
    parser.add_argument("--max-steps", type=int, default=8)
    parser.add_argument("--settle-sec", type=float, default=0.8)
    parser.add_argument("--command-seconds", type=float, default=0.45)
    parser.add_argument("--enable-motion", action="store_true")
    parser.add_argument("--enable-pitch", action="store_true")
    parser.add_argument("--stand-first", action="store_true")
    parser.add_argument("--stand-wait-sec", type=float, default=3.0)

    parser.add_argument("--target-distance-cm", type=float, default=150.0)
    parser.add_argument("--distance-tolerance-cm", type=float, default=15.0)
    parser.add_argument("--center-tolerance-ratio", type=float, default=0.12)
    parser.add_argument("--vertical-tolerance-ratio", type=float, default=0.16)
    parser.add_argument("--edge-margin-px", type=float, default=24.0)
    parser.add_argument("--forward-speed", type=float, default=0.08)
    parser.add_argument("--back-speed", type=float, default=0.08)
    parser.add_argument("--yaw-speed", type=float, default=0.12)
    parser.add_argument("--pitch-speed", type=float, default=0.04)

    parser.add_argument("--hcsr04-trigger-pin", type=int, default=DEFAULT_HCSR04_TRIGGER_PIN)
    parser.add_argument("--hcsr04-echo-pin", type=int, default=DEFAULT_HCSR04_ECHO_PIN)
    parser.add_argument("--hcsr04-samples", type=int, default=5)
    parser.add_argument("--hcsr04-sample-delay-sec", type=float, default=0.06)
    parser.add_argument("--hcsr04-max-distance-cm", type=float, default=400.0)

    parser.add_argument("--yolo-model", default=DEFAULT_MODEL)
    parser.add_argument("--yolo-confidence", type=float, default=0.35)
    parser.add_argument("--yolo-nms", type=float, default=0.45)
    parser.add_argument("--yolo-image-size", type=int, default=640)
    parser.add_argument("--person-index", type=int, default=0)

    parser.add_argument("--estimate-height", action="store_true")
    parser.add_argument("--vertical-fov-deg", type=float, default=32.5)
    parser.add_argument("--camera-pitch-deg", type=float, default=0.0)
    return parser


async def main() -> None:
    args = build_parser().parse_args()
    Path(args.output_dir).mkdir(parents=True, exist_ok=True)

    if abs(args.pitch_speed) > 0.15:
        raise RuntimeError("--pitch-speed should stay within +/-0.15 rad/s for first tests.")

    sess = None
    if args.enable_motion or args.enable_pitch or args.stand_first:
        sess = await connect_robot(args)

    results: list[dict[str, object]] = []
    try:
        if sess is not None and args.stand_first:
            print("stand_first=true", flush=True)
            print(f"stand_ret={jsonable(await sess.motion.stand())}", flush=True)
            await asyncio.sleep(args.stand_wait_sec)

        for step in range(1, args.max_steps + 1):
            distance_cm = read_distance(args)
            image_path, detections, (image_width, image_height) = capture_and_detect(args, step=step)
            person = detections[args.person_index] if len(detections) > args.person_index else None
            decision = choose_aim_decision(
                person=person,
                image_width=image_width,
                image_height=image_height,
                distance_cm=distance_cm,
                target_distance_cm=args.target_distance_cm,
                distance_tolerance_cm=args.distance_tolerance_cm,
                center_tolerance_ratio=args.center_tolerance_ratio,
                vertical_tolerance_ratio=args.vertical_tolerance_ratio,
                edge_margin_px=args.edge_margin_px,
                forward_speed=args.forward_speed,
                back_speed=args.back_speed,
                yaw_speed=args.yaw_speed,
                pitch_speed=args.pitch_speed,
            )
            height_estimate = maybe_estimate_height(
                args,
                person=person,
                image_height=image_height,
                distance_cm=distance_cm,
            )

            command_sent = "none"
            command_return = None
            if decision.action == "hold":
                command_sent = "hold"
            elif decision.has_body_motion and args.enable_motion:
                command_sent = "body_motion"
                command_return = jsonable(await stream_move(
                    sess.motion,
                    vx=decision.vx,
                    vy=decision.vy,
                    yaw=decision.yaw,
                    seconds=args.command_seconds,
                ))
            elif decision.has_pitch_motion and args.enable_pitch:
                command_sent = "pitch_motion"
                command_return = jsonable(await stream_pitch(
                    sess.motion,
                    pitch_vel=decision.pitch_vel,
                    seconds=min(args.command_seconds, 0.5),
                ))
            elif decision.has_pitch_motion and not args.enable_pitch:
                command_sent = "pitch_suggestion_only"
            else:
                command_sent = "dry_run_decision_only"

            result = {
                "step": step,
                "image": str(image_path),
                "distance_cm": distance_cm,
                "target_distance_cm": args.target_distance_cm,
                "image_width": image_width,
                "image_height": image_height,
                "detections": [asdict(detection) for detection in detections],
                "selected_person": None if person is None else asdict(person),
                "decision": asdict(decision),
                "motion_enabled": args.enable_motion,
                "pitch_enabled": args.enable_pitch,
                "command_sent": command_sent,
                "command_return": command_return,
                "height_estimate": height_estimate,
                "robot_host": args.host,
                "robot_target": args.target,
            }
            results.append(result)
            print(json.dumps(result, indent=2), flush=True)

            if decision.action == "hold":
                break
            await asyncio.sleep(max(0.0, args.settle_sec))
    finally:
        if sess is not None:
            try:
                await sess.close()
            except Exception:
                pass

    summary_path = Path(args.output_dir) / "auto_aim_summary.json"
    summary_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"summary={summary_path}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
