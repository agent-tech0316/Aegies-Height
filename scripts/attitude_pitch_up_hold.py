from __future__ import annotations

import argparse
import asyncio
import inspect
import math
import os
from typing import Any

import ff_sdk
from ff_sdk import Config


def maybe_pitch_degrees(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("pitch", "body_pitch", "pitch_rad"):
            if key in value and isinstance(value[key], (int, float)):
                return f" pitch_deg={math.degrees(float(value[key])):.2f}"
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        for idx in (1, 0):
            if isinstance(value[idx], (int, float)):
                return f" value[{idx}]_deg={math.degrees(float(value[idx])):.2f}"
    return ""


async def call_maybe_async(fn):
    value = fn()
    if inspect.isawaitable(value):
        return await value
    return value


async def print_pose(sess, label: str) -> None:
    candidates = [
        ("motion.current_pose", getattr(sess.motion, "current_pose", None)),
        ("state.pose", getattr(getattr(sess, "state", None), "pose", None)),
    ]
    for name, fn in candidates:
        if fn is None:
            continue
        try:
            value = await call_maybe_async(fn)
            print(f"{label} {name}: {value}{maybe_pitch_degrees(value)}", flush=True)
            return
        except Exception as exc:
            print(f"{label} {name}: unavailable ({type(exc).__name__}: {exc})", flush=True)
    print(f"{label} pose: unavailable", flush=True)


async def hold_pitch(sess, pitch_vel: float, seconds: float, hz: float) -> Any:
    last = None
    steps = max(1, int(seconds * hz))
    for _ in range(steps):
        last = await sess.motion.attitude_control(pitch_vel=pitch_vel)
        await asyncio.sleep(1.0 / hz)
    return last


async def neutral_stop(sess, seconds: float, hz: float) -> Any:
    last = None
    steps = max(1, int(seconds * hz))
    for _ in range(steps):
        last = await sess.motion.attitude_control()
        await asyncio.sleep(1.0 / hz)
    return last


async def hold_until_interrupted(sess, pitch_vel: float, hz: float) -> None:
    while True:
        await sess.motion.attitude_control(pitch_vel=pitch_vel)
        await asyncio.sleep(1.0 / hz)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Stand, tilt camera/head up only until Ctrl+C.")
    parser.add_argument("--target", default="D1-XG03")
    parser.add_argument("--host", default="192.168.234.1")
    parser.add_argument("--variant", default="zsl-1")
    parser.add_argument("--pitch-vel", type=float, default=0.30)
    parser.add_argument("--seconds", type=float, default=0.0, help="Optional bounded test time. Default 0 means run until Ctrl+C.")
    parser.add_argument("--stand-wait", type=float, default=10.0)
    parser.add_argument("--stop-seconds", type=float, default=0.8)
    parser.add_argument("--hz", type=float, default=20.0)
    parser.add_argument("--skip-stand", action="store_true")
    args = parser.parse_args()

    os.environ["FF_SDK_D1_HOST"] = args.host
    os.environ["FF_SDK_D1_VARIANT"] = args.variant

    sess = await ff_sdk.connect(args.target, config=Config.from_env())
    try:
        if not hasattr(sess.motion, "attitude_control"):
            raise RuntimeError("This SDK/backend does not expose motion.attitude_control().")

        if not args.skip_stand:
            print("STAND", flush=True)
            print(await sess.motion.stand(), flush=True)
            print(f"WAIT {args.stand_wait:.1f}s FOR FULL STAND", flush=True)
            await asyncio.sleep(args.stand_wait)

        await print_pose(sess, "BEFORE")

        if args.seconds > 0:
            print(f"TILT UP ONLY pitch_vel={args.pitch_vel:+.3f} seconds={args.seconds:.2f}", flush=True)
            print(await hold_pitch(sess, args.pitch_vel, args.seconds, args.hz), flush=True)
            print("DONE: bounded run finished, no neutral stop sent", flush=True)
        else:
            print(f"TILT UP ONLY pitch_vel={args.pitch_vel:+.3f}; running until Ctrl+C", flush=True)
            try:
                await hold_until_interrupted(sess, args.pitch_vel, args.hz)
            except KeyboardInterrupt:
                print("CTRL+C: neutral stop", flush=True)
                print(await neutral_stop(sess, args.stop_seconds, args.hz), flush=True)

        await print_pose(sess, "AFTER")
        print("DONE: no damping, no tilt down, no final stand reset", flush=True)
    finally:
        await sess.close()


if __name__ == "__main__":
    asyncio.run(main())
