"""Probe dog tilt telemetry, attitude control, camera capture, and YOLO person detection.

Run this on the robot or on a Linux machine connected to the robot network.
It checks whether the Python backend exposes pitch telemetry and attitude
control strongly enough for camera-only height measurement.

Developer notes:
  - motion.attitude_control(roll_vel, pitch_vel, yaw_vel, height_vel) uses physical units.
  - attitude_control is D1/quadruped-only.
  - roll/pitch/yaw velocity units are rad/s, valid API range about -0.5..0.5.
  - height velocity is m/s, valid API range about -0.5..0.5.
  - negative pitch_vel means head/camera pitches downward in the current D1 joystick mapping.
  - keep pitch tests small first: about +/-0.10..0.15 rad/s for short bursts.
  - rpy() returns [roll, pitch, yaw] in radians for body/IMU pose, not camera-only pitch.
  - the camera is fixed to the body, so camera pitch = body pitch + measured mount offset.
"""
from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import os
import sys
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path

from height_calculator import (
    DEFAULT_MODEL,
    DEFAULT_RTSP_URL,
    capture_one_frame,
    detect_people_yolo,
)


RECOMMENDED_MAX_TEST_PITCH_VEL = 0.15


async def call_if_available(obj, name: str):
    method = getattr(obj, name, None)
    if method is None:
        return {"available": False}
    try:
        value = method()
        if inspect.isawaitable(value):
            value = await value
        return {"available": True, "value": value}
    except Exception as exc:  # noqa: BLE001 - this is a diagnostic probe.
        return {"available": True, "error": f"{type(exc).__name__}: {exc}"}


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


async def stream_attitude(motion, *, pitch_vel: float, seconds: float, interval_sec: float) -> dict[str, object]:
    attitude_control = getattr(motion, "attitude_control", None)
    if attitude_control is None:
        return {"available": False, "sent": 0}

    sent = 0
    last_ret = None
    end = time.monotonic() + max(0.0, seconds)
    while time.monotonic() < end:
        last_ret = await attitude_control(pitch_vel=pitch_vel)
        sent += 1
        await asyncio.sleep(interval_sec)

    stop_end = time.monotonic() + 0.4
    while time.monotonic() < stop_end:
        last_ret = await attitude_control()
        sent += 1
        await asyncio.sleep(interval_sec)

    return {"available": True, "sent": sent, "last_return": jsonable(last_ret)}


def capture_and_detect(args: argparse.Namespace, label: str) -> dict[str, object]:
    image_path = Path(args.output_dir) / f"{label}.jpg"
    capture_one_frame(rtsp_url=args.rtsp_url, output=image_path, jpeg_quality=args.jpeg_quality)
    detections = detect_people_yolo(
        image_path,
        model_path=Path(args.yolo_model),
        confidence_threshold=args.yolo_confidence,
        nms_threshold=args.yolo_nms,
        image_size=args.yolo_image_size,
    )
    return {
        "image": str(image_path),
        "detections": [asdict(detection) for detection in detections],
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default=os.environ.get("FF_SDK_TARGET", "D1-XG03"))
    parser.add_argument("--host", default=os.environ.get("FF_SDK_D1_HOST", "192.168.234.1"))
    parser.add_argument("--variant", default=os.environ.get("FF_SDK_D1_VARIANT", "zsl-1"))
    parser.add_argument("--local-port", type=int, default=43988)
    parser.add_argument("--rtsp-url", default=DEFAULT_RTSP_URL)
    parser.add_argument("--output-dir", default="tilt_probe_runs/latest")
    parser.add_argument("--jpeg-quality", type=int, default=92)
    parser.add_argument("--stand", action="store_true", help="Call stand_up before probing.")
    parser.add_argument("--stand-wait-sec", type=float, default=3.0)
    parser.add_argument(
        "--pitch-vel",
        type=float,
        default=-0.08,
        help="Pitch velocity in rad/s. Negative pitches the head/camera downward on D1.",
    )
    parser.add_argument("--pitch-seconds", type=float, default=0.8)
    parser.add_argument("--interval-sec", type=float, default=0.05)
    parser.add_argument("--skip-tilt", action="store_true")
    parser.add_argument("--yolo-model", default=DEFAULT_MODEL)
    parser.add_argument("--yolo-confidence", type=float, default=0.35)
    parser.add_argument("--yolo-nms", type=float, default=0.45)
    parser.add_argument("--yolo-image-size", type=int, default=640)
    args = parser.parse_args()

    if abs(args.pitch_vel) > RECOMMENDED_MAX_TEST_PITCH_VEL:
        print(
            "WARNING: pitch_vel is above the recommended first-test limit "
            f"(+/-{RECOMMENDED_MAX_TEST_PITCH_VEL} rad/s). Keep the robot clear "
            "and use short bursts.",
            file=sys.stderr,
        )

    Path(args.output_dir).mkdir(parents=True, exist_ok=True)

    try:
        import ff_sdk
        from ff_sdk import Config
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "This probe must run where ff_sdk is installed, usually on the robot "
            "or a Linux machine with the SDK wheel installed."
        ) from exc

    os.environ["FF_SDK_D1_HOST"] = args.host
    os.environ["FF_SDK_D1_VARIANT"] = args.variant

    report: dict[str, object] = {
        "target": args.target,
        "host": args.host,
        "variant": args.variant,
        "rtsp_url": args.rtsp_url,
        "pitch_vel_command": args.pitch_vel,
        "pitch_seconds": args.pitch_seconds,
        "pitch_vel_units": "rad/s",
        "negative_pitch_vel": "head_down",
        "rpy_units": "rad",
        "rpy_source": "body_imu_pose_not_camera_only_pitch",
        "camera_mount": "fixed_to_body_measure_mount_offset_on_real_robot",
    }

    sess = None
    try:
        sess = await ff_sdk.connect(args.target, config=Config.from_env())
        report["connected"] = True
        report["capabilities"] = sorted(sess.capabilities())

        public_methods = [name for name in dir(sess.motion) if not name.startswith("_")]
        report["available_motion_methods"] = public_methods
        report["battery"] = await call_if_available(sess.state, "battery")
        report["initial_status"] = await call_if_available(sess.state, "status")
        report["initial_pose"] = await call_if_available(sess.state, "pose")

        if args.stand:
            report["stand_return"] = jsonable(await sess.motion.stand())
            await asyncio.sleep(args.stand_wait_sec)
            report["after_stand_status"] = await call_if_available(sess.state, "status")
            report["after_stand_pose"] = await call_if_available(sess.state, "pose")

        report["before_image"] = capture_and_detect(args, "before_tilt")

        if args.skip_tilt:
            report["tilt_command"] = {"skipped": True}
        else:
            report["tilt_command"] = await stream_attitude(
                sess.motion,
                pitch_vel=args.pitch_vel,
                seconds=args.pitch_seconds,
                interval_sec=args.interval_sec,
            )
            await asyncio.sleep(0.5)

        report["after_tilt_pose"] = await call_if_available(sess.state, "pose")
        report["after_image"] = capture_and_detect(args, "after_tilt")
    finally:
        if sess is not None:
            try:
                await sess.close()
            except Exception:
                pass

    print(json.dumps(jsonable(report), indent=2))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:  # noqa: BLE001 - command-line diagnostic.
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
