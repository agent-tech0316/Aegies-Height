from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import ff_sdk
from ff_sdk import Config


ROOT = Path(__file__).resolve().parents[1]
VISION_DIR = ROOT / "examples" / "vision"
if str(VISION_DIR) not in sys.path:
    sys.path.insert(0, str(VISION_DIR))

from codey_pitch import read_codey_pitch


async def hold_pitch(sess, *, pitch_vel: float, seconds: float, hz: float):
    last = None
    steps = max(1, int(round(max(0.05, seconds) * max(1.0, hz))))
    delay = 1.0 / max(1.0, hz)
    for _ in range(steps):
        last = await sess.motion.attitude_control(pitch_vel=pitch_vel)
        await asyncio.sleep(delay)
    return last


async def neutral_stop(sess, *, seconds: float, hz: float):
    last = None
    steps = max(1, int(round(max(0.05, seconds) * max(1.0, hz))))
    delay = 1.0 / max(1.0, hz)
    for _ in range(steps):
        last = await sess.motion.attitude_control()
        await asyncio.sleep(delay)
    return last


def with_relative_pitch(reading: dict[str, object] | None, zero_deg: float | None) -> dict[str, object] | None:
    if reading is None or zero_deg is None:
        return reading
    reading["zero_deg"] = zero_deg
    reading["relative_pitch_deg"] = float(reading["pitch_deg"]) - zero_deg
    return reading


def codey_snapshot(
    args: argparse.Namespace,
    label: str,
    *,
    zero_deg: float | None = None,
) -> dict[str, object] | None:
    if not args.codey:
        return None
    try:
        reading = read_codey_pitch(
            port=args.codey_port or None,
            baud=args.codey_baud,
            samples=args.codey_samples,
            timeout_sec=args.codey_timeout_sec,
        )
        reading["label"] = label
        with_relative_pitch(reading, zero_deg)
        print("CODEY_PITCH " + json.dumps(reading, sort_keys=True), flush=True)
        return reading
    except Exception as exc:
        payload = {"label": label, "error": f"{type(exc).__name__}: {exc}"}
        print("CODEY_PITCH_ERROR " + json.dumps(payload, sort_keys=True), flush=True)
        if args.codey_required:
            raise
        return None


def pitch_deg(reading: dict[str, object] | None) -> float | None:
    if not reading:
        return None
    value = reading.get("pitch_deg")
    if value is None:
        return None
    return float(value)


def relative_pitch_deg(reading: dict[str, object] | None, zero_deg: float | None) -> float | None:
    if not reading:
        return None
    value = reading.get("relative_pitch_deg")
    if value is not None:
        return float(value)
    raw = pitch_deg(reading)
    if raw is None or zero_deg is None:
        return None
    return raw - zero_deg


async def main() -> None:
    parser = argparse.ArgumentParser(description="One bounded D1 pitch step; no damping, no lie-down.")
    parser.add_argument("--target", default="D1-XG03")
    parser.add_argument("--host", default="192.168.234.1")
    parser.add_argument("--variant", default="zsl-1")
    parser.add_argument("--pitch-vel", type=float, required=True)
    parser.add_argument("--seconds", type=float, default=3.0)
    parser.add_argument("--hz", type=float, default=20.0)
    parser.add_argument("--stand-wait", type=float, default=10.0)
    parser.add_argument("--stop-seconds", type=float, default=0.8)
    parser.add_argument("--skip-stand", action="store_true")
    parser.add_argument("--codey", action="store_true", help="Read Codey Rocky pitch before/after the pitch step.")
    parser.add_argument("--codey-required", action="store_true", help="Fail if Codey pitch cannot be read.")
    parser.add_argument("--codey-port", default="", help="Usually /dev/ttyUSB0 or /dev/ttyACM0. Empty auto-detects.")
    parser.add_argument("--codey-baud", type=int, default=115200)
    parser.add_argument("--codey-samples", type=int, default=3)
    parser.add_argument("--codey-timeout-sec", type=float, default=5.0)
    parser.add_argument(
        "--codey-zero-deg",
        type=float,
        default=None,
        help="Raw Codey pitch that means standing neutral. If omitted, after-stand/before-step reading becomes 0.",
    )
    parser.add_argument(
        "--close-session-on-exit",
        action="store_true",
        help=(
            "Explicitly close the ff_sdk session before exiting. Disabled by default because "
            "this robot backend can treat close() like a damping/safe-stop transition."
        ),
    )
    args = parser.parse_args()

    os.environ["FF_SDK_D1_HOST"] = args.host
    os.environ["FF_SDK_D1_VARIANT"] = args.variant

    sess = await ff_sdk.connect(args.target, config=Config.from_env())
    try:
        initial_pitch = codey_snapshot(args, "initial")
        after_stand_pitch = None
        if not args.skip_stand:
            print("STAND", flush=True)
            print(await sess.motion.stand(), flush=True)
            print(f"WAIT {args.stand_wait:.1f}s FOR FULL STAND", flush=True)
            await asyncio.sleep(max(0.0, args.stand_wait))
            after_stand_pitch = codey_snapshot(args, "after_stand")

        before_step_pitch = codey_snapshot(args, "before_step")
        zero_deg = args.codey_zero_deg
        zero_source = "argument"
        if zero_deg is None:
            zero_deg = pitch_deg(after_stand_pitch)
            zero_source = "after_stand"
        if zero_deg is None:
            zero_deg = pitch_deg(before_step_pitch)
            zero_source = "before_step"
        if zero_deg is None:
            zero_deg = pitch_deg(initial_pitch)
            zero_source = "initial"
        if zero_deg is not None:
            print("CODEY_ZERO " + json.dumps({"zero_deg": zero_deg, "source": zero_source}, sort_keys=True), flush=True)
            if after_stand_pitch is not None:
                with_relative_pitch(after_stand_pitch, zero_deg)
                print("CODEY_PITCH_RELATIVE " + json.dumps(after_stand_pitch, sort_keys=True), flush=True)
            if before_step_pitch is not None:
                with_relative_pitch(before_step_pitch, zero_deg)
                print("CODEY_PITCH_RELATIVE " + json.dumps(before_step_pitch, sort_keys=True), flush=True)

        print(f"PITCH_STEP pitch_vel={args.pitch_vel:+.3f} seconds={args.seconds:.2f}", flush=True)
        print(await hold_pitch(sess, pitch_vel=args.pitch_vel, seconds=args.seconds, hz=args.hz), flush=True)
        after_step_pitch = codey_snapshot(args, "after_step", zero_deg=zero_deg)
        print(f"NEUTRAL_STOP seconds={args.stop_seconds:.2f}", flush=True)
        print(await neutral_stop(sess, seconds=args.stop_seconds, hz=args.hz), flush=True)
        after_stop_pitch = codey_snapshot(args, "after_stop", zero_deg=zero_deg)

        before_raw_value = pitch_deg(before_step_pitch) if before_step_pitch else pitch_deg(after_stand_pitch)
        after_raw_value = pitch_deg(after_step_pitch) if after_step_pitch else pitch_deg(after_stop_pitch)
        before_value = relative_pitch_deg(before_step_pitch, zero_deg)
        if before_value is None:
            before_value = relative_pitch_deg(after_stand_pitch, zero_deg)
        if before_value is None:
            before_value = relative_pitch_deg(initial_pitch, zero_deg)
        after_value = relative_pitch_deg(after_step_pitch, zero_deg)
        if after_value is None:
            after_value = relative_pitch_deg(after_stop_pitch, zero_deg)
        delta_value = None if before_value is None or after_value is None else after_value - before_value
        summary = {
            "pitch_vel": args.pitch_vel,
            "seconds": args.seconds,
            "codey_zero_deg": zero_deg,
            "codey_zero_source": zero_source if zero_deg is not None else None,
            "before_step_raw_deg": before_raw_value,
            "after_step_raw_deg": after_raw_value,
            "after_stop_raw_deg": pitch_deg(after_stop_pitch),
            "before_step_relative_deg": before_value,
            "after_step_relative_deg": after_value,
            "after_stop_relative_deg": relative_pitch_deg(after_stop_pitch, zero_deg),
            "delta_deg": delta_value,
            "abs_delta_deg": None if delta_value is None else abs(delta_value),
            "measured_deg_per_sec": None if delta_value is None else delta_value / max(1e-6, args.seconds),
        }
        print("PITCH_STEP_SUMMARY " + json.dumps(summary, sort_keys=True), flush=True)
    finally:
        if args.close_session_on_exit:
            await sess.close()
        else:
            print("LEAVE_STANDING_NO_SDK_CLOSE", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
