"""Probe dog tilt telemetry, attitude control, camera capture, and YOLO person detection.

Run this on the robot or on a Linux machine connected to the robot network.
It checks whether the Python backend exposes pitch telemetry and attitude
control strongly enough for camera-only height measurement.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path

from height_calculator import (
    DEFAULT_MODEL,
    DEFAULT_RTSP_URL,
    capture_one_frame,
    detect_people_yolo,
)


def call_if_available(obj, name: str):
    method = getattr(obj, name, None)
    if method is None:
        return {"available": False}
    try:
        value = method()
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
    return repr(value)


def stream_attitude(dog, *, pitch_vel: float, seconds: float, interval_sec: float) -> dict[str, object]:
    attitude = getattr(dog, "attitude", None)
    if attitude is None:
        return {"available": False, "sent": 0}

    sent = 0
    last_ret = None
    end = time.monotonic() + max(0.0, seconds)
    while time.monotonic() < end:
        last_ret = attitude(0.0, pitch_vel, 0.0, 0.0)
        sent += 1
        time.sleep(interval_sec)

    stop_end = time.monotonic() + 0.4
    while time.monotonic() < stop_end:
        last_ret = attitude(0.0, 0.0, 0.0, 0.0)
        sent += 1
        time.sleep(interval_sec)

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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("FF_SDK_D1_HOST", "192.168.234.1"))
    parser.add_argument("--variant", default=os.environ.get("FF_SDK_D1_VARIANT", "zsl-1"))
    parser.add_argument("--local-port", type=int, default=43988)
    parser.add_argument("--rtsp-url", default=DEFAULT_RTSP_URL)
    parser.add_argument("--output-dir", default="tilt_probe_runs/latest")
    parser.add_argument("--jpeg-quality", type=int, default=92)
    parser.add_argument("--stand", action="store_true", help="Call stand_up before probing.")
    parser.add_argument("--stand-wait-sec", type=float, default=3.0)
    parser.add_argument("--pitch-vel", type=float, default=0.08)
    parser.add_argument("--pitch-seconds", type=float, default=0.8)
    parser.add_argument("--interval-sec", type=float, default=0.05)
    parser.add_argument("--skip-tilt", action="store_true")
    parser.add_argument("--yolo-model", default=DEFAULT_MODEL)
    parser.add_argument("--yolo-confidence", type=float, default=0.35)
    parser.add_argument("--yolo-nms", type=float, default=0.45)
    parser.add_argument("--yolo-image-size", type=int, default=640)
    args = parser.parse_args()

    Path(args.output_dir).mkdir(parents=True, exist_ok=True)

    try:
        from ff_sdk.internal.oem.zsibot import ZsibotClient, detect_local_ip
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "This probe must run where ff_sdk is installed, usually on the robot "
            "or a Linux machine with the SDK wheel installed."
        ) from exc

    local_ip = detect_local_ip(args.host)
    dog = ZsibotClient(
        dog_ip=args.host,
        local_ip=local_ip,
        local_port=args.local_port,
        variant=args.variant,
    )

    report: dict[str, object] = {
        "host": args.host,
        "local_ip": local_ip,
        "variant": args.variant,
        "rtsp_url": args.rtsp_url,
        "pitch_vel_command": args.pitch_vel,
        "pitch_seconds": args.pitch_seconds,
    }

    try:
        connected = dog.connect(settle_timeout=5.0)
        report["connected"] = connected
        if not connected:
            raise RuntimeError("zsibot backend did not connect")

        public_methods = [name for name in dir(dog) if not name.startswith("_")]
        report["available_methods"] = public_methods
        report["battery"] = call_if_available(dog, "battery")
        report["initial_ctrl_mode"] = call_if_available(dog, "ctrl_mode")
        report["initial_rpy"] = call_if_available(dog, "rpy")
        report["initial_position"] = call_if_available(dog, "position")

        if args.stand:
            report["stand_up_return"] = jsonable(dog.stand_up())
            time.sleep(args.stand_wait_sec)
            report["after_stand_ctrl_mode"] = call_if_available(dog, "ctrl_mode")
            report["after_stand_rpy"] = call_if_available(dog, "rpy")

        report["before_image"] = capture_and_detect(args, "before_tilt")

        if args.skip_tilt:
            report["tilt_command"] = {"skipped": True}
        else:
            report["tilt_command"] = stream_attitude(
                dog,
                pitch_vel=args.pitch_vel,
                seconds=args.pitch_seconds,
                interval_sec=args.interval_sec,
            )
            time.sleep(0.5)

        report["after_tilt_rpy"] = call_if_available(dog, "rpy")
        report["after_tilt_position"] = call_if_available(dog, "position")
        report["after_image"] = capture_and_detect(args, "after_tilt")
    finally:
        try:
            dog.close()
        except Exception:
            pass

    print(json.dumps(jsonable(report), indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - command-line diagnostic.
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
