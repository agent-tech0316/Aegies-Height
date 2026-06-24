"""Run a verified D1 movement sequence through the public ff_sdk D1 backend.

Sequence:
    stand -> zero warmup -> forward -> back -> left -> right -> zero stop

Usage:
    python examples/d1/raw_zsibot_sequence.py
"""
from __future__ import annotations

import argparse
import asyncio
import os
import time


def jsonable(value):
    if hasattr(value, "__dataclass_fields__"):
        from dataclasses import asdict

        return asdict(value)
    return value


async def stream_move(
    sess,
    *,
    label: str,
    vx: float,
    vy: float,
    yaw: float,
    seconds: float,
) -> int | None:
    print(f">> {label}: vx={vx:.2f}, vy={vy:.2f}, yaw={yaw:.2f}, seconds={seconds:.1f}")
    end = time.monotonic() + max(0.0, seconds)
    last_ret = None
    while time.monotonic() < end:
        last_ret = await sess.motion.cmd_vel(linear=vx, lateral=vy, angular=yaw)
        await asyncio.sleep(0.05)
    print(f"{label}_ret={jsonable(last_ret)}")
    print(f"{label}_status={jsonable(await sess.state.status())}")
    print(f"{label}_pose={jsonable(await sess.state.pose())}")
    return last_ret


async def zero_velocity(sess, seconds: float):
    return await stream_move(
        sess,
        label="zero",
        vx=0.0,
        vy=0.0,
        yaw=0.0,
        seconds=seconds,
    )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default=os.environ.get("FF_SDK_TARGET", "D1-XG03"))
    parser.add_argument("--host", default="192.168.234.1")
    parser.add_argument("--variant", default="zsl-1")
    parser.add_argument("--local-ip", default=None, help="Accepted for old commands; public ff_sdk auto-detects it.")
    parser.add_argument("--stand-wait", type=float, default=3.0)
    parser.add_argument("--warmup-seconds", type=float, default=1.0)
    parser.add_argument("--move-seconds", type=float, default=1.2)
    parser.add_argument("--zero-seconds", type=float, default=1.0)
    parser.add_argument("--forward-speed", type=float, default=0.35)
    parser.add_argument("--back-speed", type=float, default=0.25)
    parser.add_argument("--lateral-speed", type=float, default=0.18)
    args = parser.parse_args()

    moves = [
        ("forward", args.forward_speed, 0.0, 0.0),
        ("back", -args.back_speed, 0.0, 0.0),
        ("left", 0.0, args.lateral_speed, 0.0),
        ("right", 0.0, -args.lateral_speed, 0.0),
    ]

    try:
        import ff_sdk
        from ff_sdk import Config
    except ModuleNotFoundError as exc:
        raise RuntimeError("Install the updated ff_sdk wheel before running this command.") from exc

    os.environ["FF_SDK_D1_HOST"] = args.host
    os.environ["FF_SDK_D1_VARIANT"] = args.variant

    sess = None
    try:
        sess = await ff_sdk.connect(args.target, config=Config.from_env())
        print("sequence=stand_forward_back_left_right")
        print(f"robot_target={args.target}")
        print(f"robot_host={args.host}")
        print(f"variant={args.variant}")
        if args.local_ip:
            print(f"local_ip_ignored={args.local_ip}")
        print("connected=true")

        print(f"battery={jsonable(await sess.state.battery())}")
        print(f"initial_status={jsonable(await sess.state.status())}")

        print(">> stand")
        print(f"stand_ret={jsonable(await sess.motion.stand())}")
        await asyncio.sleep(args.stand_wait)
        print(f"status_after_stand={jsonable(await sess.state.status())}")

        print(">> zero warmup")
        await zero_velocity(sess, args.warmup_seconds)

        for label, vx, vy, yaw in moves:
            await stream_move(
                sess,
                label=label,
                vx=vx,
                vy=vy,
                yaw=yaw,
                seconds=args.move_seconds,
            )
            await zero_velocity(sess, args.zero_seconds)

        print(f"final_status={jsonable(await sess.state.status())}")
        print(f"final_pose={jsonable(await sess.state.pose())}")
    finally:
        if sess is not None:
            await sess.close()


if __name__ == "__main__":
    asyncio.run(main())
