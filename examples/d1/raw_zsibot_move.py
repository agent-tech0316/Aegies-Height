"""Simple verified D1 movement commands using the public ff_sdk D1 backend.

The command pattern is:

    stand -> wait -> zero warmup -> stream move -> zero stop

Usage:
    python examples/d1/raw_zsibot_move.py forward
    python examples/d1/raw_zsibot_move.py back
    python examples/d1/raw_zsibot_move.py left
    python examples/d1/raw_zsibot_move.py right
"""
from __future__ import annotations

import argparse
import asyncio
import os
import time


MOVES = {
    "forward": (0.35, 0.0, 0.0),
    "back": (-0.25, 0.0, 0.0),
    "backward": (-0.25, 0.0, 0.0),
    "left": (0.0, 0.18, 0.0),
    "right": (0.0, -0.18, 0.0),
    "yaw_left": (0.0, 0.0, 0.25),
    "yaw_right": (0.0, 0.0, -0.25),
    "zero": (0.0, 0.0, 0.0),
}


def jsonable(value):
    if hasattr(value, "__dataclass_fields__"):
        from dataclasses import asdict

        return asdict(value)
    return value


async def stream_move(motion, vx: float, vy: float, yaw: float, seconds: float):
    end = time.monotonic() + max(0.0, seconds)
    last_ret = None
    while time.monotonic() < end:
        last_ret = await motion.cmd_vel(linear=vx, lateral=vy, angular=yaw)
        await asyncio.sleep(0.05)
    return last_ret


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("direction", choices=sorted(MOVES))
    parser.add_argument("--target", default=os.environ.get("FF_SDK_TARGET", "D1-XG03"))
    parser.add_argument("--host", default="192.168.234.1")
    parser.add_argument("--variant", default="zsl-1")
    parser.add_argument("--local-ip", default=None, help="Accepted for old commands; public ff_sdk auto-detects it.")
    parser.add_argument("--seconds", type=float, default=1.2)
    parser.add_argument("--stand-wait", type=float, default=3.0)
    parser.add_argument("--skip-stand", action="store_true")
    parser.add_argument("--pre-move-delay", type=float, default=0.0)
    parser.add_argument("--warmup-seconds", type=float, default=1.0)
    parser.add_argument("--stop-seconds", type=float, default=1.0)
    args = parser.parse_args()

    vx, vy, yaw = MOVES[args.direction]
    if args.direction == "zero":
        args.seconds = max(args.seconds, 1.0)

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
        print(f"move_direction={args.direction}")
        print(f"robot_target={args.target}")
        print(f"robot_host={args.host}")
        print(f"variant={args.variant}")
        if args.local_ip:
            print(f"local_ip_ignored={args.local_ip}")
        print("connected=true")

        print(f"battery={jsonable(await sess.state.battery())}")
        print(f"initial_status={jsonable(await sess.state.status())}")
        if args.skip_stand:
            print("stand=skipped")
        else:
            print("stand=true")
            print(f"stand_ret={jsonable(await sess.motion.stand())}")
            await asyncio.sleep(args.stand_wait)
            print(f"status_after_stand={jsonable(await sess.state.status())}")

        if args.pre_move_delay > 0:
            print(f"pre_move_delay={args.pre_move_delay}")
            await asyncio.sleep(args.pre_move_delay)

        print("zero_warmup=true")
        print(
            "zero_warmup_ret="
            f"{jsonable(await stream_move(sess.motion, 0.0, 0.0, 0.0, args.warmup_seconds))}"
        )

        print(f"move_vx={vx}")
        print(f"move_vy={vy}")
        print(f"move_yaw={yaw}")
        print(f"move_seconds={args.seconds}")
        print(f"move_ret={jsonable(await stream_move(sess.motion, vx, vy, yaw, args.seconds))}")
        print(f"status_after_move={jsonable(await sess.state.status())}")
        print(f"pose_after_move={jsonable(await sess.state.pose())}")

        print("zero_stop=true")
        print(f"zero_stop_ret={jsonable(await stream_move(sess.motion, 0.0, 0.0, 0.0, args.stop_seconds))}")
        print(f"final_status={jsonable(await sess.state.status())}")
    finally:
        if sess is not None:
            await sess.close()


if __name__ == "__main__":
    asyncio.run(main())
