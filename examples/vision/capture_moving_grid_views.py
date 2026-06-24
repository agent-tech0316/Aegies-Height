"""Capture lights-on grid images from several dog positions.

This script is for camera calibration, not laser calibration. It captures the
wall grid with the lights on, then optionally moves the dog in small safe steps
and captures more views.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from datetime import datetime
from pathlib import Path

from grid_laser_calibration import (
    DEFAULT_RTSP_URL,
    capture_one_frame_with_timeout,
    require_cv2_numpy,
    write_image_or_raise,
)


def jsonable(value):
    if hasattr(value, "__dataclass_fields__"):
        from dataclasses import asdict

        return asdict(value)
    return value


async def stream_move(motion, *, label: str, vx: float, vy: float, yaw: float, seconds: float):
    print(f"move={label} vx={vx:.3f} vy={vy:.3f} yaw={yaw:.3f} seconds={seconds:.2f}", flush=True)
    end = time.monotonic() + max(0.0, seconds)
    last_ret = None
    while time.monotonic() < end:
        last_ret = await motion.cmd_vel(linear=vx, lateral=vy, angular=yaw)
        await asyncio.sleep(0.05)
    return last_ret


async def zero_velocity(motion, seconds: float):
    return await stream_move(motion, label="zero", vx=0.0, vy=0.0, yaw=0.0, seconds=seconds)


async def connect_dog(args: argparse.Namespace):
    import ff_sdk
    from ff_sdk import Config

    os.environ["FF_SDK_D1_HOST"] = args.host
    os.environ["FF_SDK_D1_VARIANT"] = args.variant
    print(f"robot_host={args.host}", flush=True)
    print(f"robot_target={args.target}", flush=True)
    print(f"variant={args.variant}", flush=True)
    sess = await ff_sdk.connect(args.target, config=Config.from_env())
    print("connected=true", flush=True)
    return sess


def capture_view(args: argparse.Namespace, output_dir: Path, label: str, index: int) -> dict[str, object]:
    cv2, _ = require_cv2_numpy()
    raw_path = output_dir / f"{index:02d}_{label}.jpg"
    annotated_path = output_dir / f"{index:02d}_{label}_annotated.jpg"
    print(f"capture={label} output={raw_path}", flush=True)
    capture_one_frame_with_timeout(
        rtsp_url=args.rtsp_url,
        output=raw_path,
        jpeg_quality=args.jpeg_quality,
        timeout_sec=args.capture_timeout_sec,
    )
    image = cv2.imread(str(raw_path))
    if image is None:
        raise RuntimeError(f"OpenCV could not read captured image: {raw_path}")
    annotated = image.copy()
    cv2.putText(
        annotated,
        label,
        (30, 50),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.2,
        (255, 255, 255),
        4,
        cv2.LINE_AA,
    )
    cv2.putText(
        annotated,
        label,
        (30, 50),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.2,
        (0, 0, 0),
        1,
        cv2.LINE_AA,
    )
    write_image_or_raise(annotated_path, annotated, args.jpeg_quality)
    return {
        "index": index,
        "label": label,
        "image": str(raw_path),
        "annotated_image": str(annotated_path),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }


def default_plan(args: argparse.Namespace) -> list[tuple[str, float, float, float, float]]:
    return [
        ("center", 0.0, 0.0, 0.0, 0.0),
        ("left", 0.0, args.lateral_speed, 0.0, args.move_seconds),
        ("right", 0.0, -args.lateral_speed, 0.0, args.move_seconds * 2.0),
        ("center_after_right", 0.0, args.lateral_speed, 0.0, args.move_seconds),
        ("closer", args.forward_speed, 0.0, 0.0, args.move_seconds),
        ("farther", -args.back_speed, 0.0, 0.0, args.move_seconds * 2.0),
        ("center_after_farther", args.forward_speed, 0.0, 0.0, args.move_seconds),
    ]


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="camera_calibration_runs/latest/moving_grid_images")
    parser.add_argument("--rtsp-url", default=DEFAULT_RTSP_URL)
    parser.add_argument("--capture-timeout-sec", type=float, default=8.0)
    parser.add_argument("--jpeg-quality", type=int, default=95)
    parser.add_argument("--settle-seconds", type=float, default=1.0)
    parser.add_argument("--enable-motion", action="store_true")
    parser.add_argument("--target", default=os.environ.get("FF_SDK_TARGET", "D1-XG03"))
    parser.add_argument("--host", default="192.168.234.1")
    parser.add_argument("--variant", default="zsl-1")
    parser.add_argument("--local-port", type=int, default=43988)
    parser.add_argument("--stand-wait", type=float, default=3.0)
    parser.add_argument("--warmup-seconds", type=float, default=0.8)
    parser.add_argument("--stop-seconds", type=float, default=0.8)
    parser.add_argument("--move-seconds", type=float, default=0.65)
    parser.add_argument("--lateral-speed", type=float, default=0.10)
    parser.add_argument("--forward-speed", type=float, default=0.10)
    parser.add_argument("--back-speed", type=float, default=0.10)
    parser.add_argument(
        "--distance-to-grid-center",
        default="10ft11in",
        help="Measured dog-camera to grid center distance for notes only.",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    records: list[dict[str, object]] = []
    sess = None

    try:
        if args.enable_motion:
            sess = await connect_dog(args)
            print(f"battery={jsonable(await sess.state.battery())}", flush=True)
            print("stand=true", flush=True)
            print(f"stand_ret={jsonable(await sess.motion.stand())}", flush=True)
            await asyncio.sleep(args.stand_wait)
            await zero_velocity(sess.motion, args.warmup_seconds)
        else:
            print("motion_disabled=true capture_only=true", flush=True)

        for index, (label, vx, vy, yaw, seconds) in enumerate(default_plan(args), start=1):
            if sess is not None and seconds > 0:
                ret = await stream_move(sess.motion, label=label, vx=vx, vy=vy, yaw=yaw, seconds=seconds)
                await zero_velocity(sess.motion, args.stop_seconds)
                print(f"{label}_move_ret={jsonable(ret)}", flush=True)
                await asyncio.sleep(args.settle_seconds)
            elif index > 1 and sess is None:
                input(f"Move dog/view for '{label}', then press Enter to capture> ")
            records.append(capture_view(args, output_dir, label, index))
    finally:
        if sess is not None:
            await zero_velocity(sess.motion, args.stop_seconds)
            await sess.close()

    manifest = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "motion_enabled": args.enable_motion,
        "output_dir": str(output_dir),
        "distance_to_grid_center": args.distance_to_grid_center,
        "records": records,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"manifest={manifest_path}", flush=True)
    print(f"captured_count={len(records)}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
