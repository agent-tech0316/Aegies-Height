#!/usr/bin/env python3
"""Small robot-side motion server for Pi-triggered commands.

Runs on the robot. It keeps one ff_sdk session open and accepts one-line JSON
commands over TCP. It never calls damping or lie_down.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from typing import Any


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen-host", default="0.0.0.0")
    parser.add_argument("--listen-port", type=int, default=45100)
    parser.add_argument("--target", default="D1-demo")
    parser.add_argument("--robot-host", default="192.168.234.1")
    parser.add_argument("--robot-variant", default="zsl-1")
    return parser


async def hold_velocity(motion: Any, *, linear: float, lateral: float, angular: float, seconds: float, hz: float) -> None:
    interval = 1.0 / hz
    loops = max(1, int(round(seconds * hz)))
    for _ in range(loops):
        await motion.cmd_vel(linear=linear, lateral=lateral, angular=angular)
        await asyncio.sleep(interval)


async def zero_velocity(motion: Any, *, seconds: float, hz: float) -> None:
    await hold_velocity(motion, linear=0.0, lateral=0.0, angular=0.0, seconds=seconds, hz=hz)


async def hold_attitude(motion: Any, *, pitch_vel: float, seconds: float, hz: float) -> None:
    if not hasattr(motion, "attitude_control"):
        raise RuntimeError("ff_sdk motion object has no attitude_control()")
    interval = 1.0 / hz
    loops = max(1, int(round(seconds * hz)))
    for _ in range(loops):
        await motion.attitude_control(pitch_vel=pitch_vel)
        await asyncio.sleep(interval)


async def release_attitude(motion: Any, *, seconds: float, hz: float) -> None:
    if not hasattr(motion, "attitude_control"):
        raise RuntimeError("ff_sdk motion object has no attitude_control()")
    interval = 1.0 / hz
    loops = max(1, int(round(seconds * hz)))
    for _ in range(loops):
        await motion.attitude_control()
        await asyncio.sleep(interval)


async def main_async() -> int:
    args = build_parser().parse_args()
    os.environ["FF_SDK_D1_HOST"] = args.robot_host
    os.environ["FF_SDK_D1_VARIANT"] = args.robot_variant

    import ff_sdk
    from ff_sdk import Config

    sess = await ff_sdk.connect(args.target, config=Config.from_env())
    print(
        "ROBOT_MOTION_SERVER_READY "
        f"target={args.target} host={args.robot_host} variant={args.robot_variant} "
        f"attitude={hasattr(sess.motion, 'attitude_control')}",
        flush=True,
    )

    async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        started = time.monotonic()
        response: dict[str, Any]
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=5.0)
            request = json.loads(line.decode("utf-8"))
            command = request.get("cmd")
            hz = float(request.get("hz", 20.0))
            seconds = float(request.get("seconds", 0.1))

            if command == "ping":
                response = {
                    "ok": True,
                    "attitude": hasattr(sess.motion, "attitude_control"),
                    "methods": [name for name in dir(sess.motion) if "attitude" in name or "stand" in name or "cmd" in name],
                }
            elif command == "stand":
                result = await sess.motion.stand()
                response = {"ok": True, "result": repr(result)}
            elif command == "velocity_hold":
                await hold_velocity(
                    sess.motion,
                    linear=float(request.get("linear", 0.0)),
                    lateral=float(request.get("lateral", 0.0)),
                    angular=float(request.get("angular", 0.0)),
                    seconds=seconds,
                    hz=hz,
                )
                response = {"ok": True}
            elif command == "zero_velocity":
                await zero_velocity(sess.motion, seconds=seconds, hz=hz)
                response = {"ok": True}
            elif command == "attitude_hold":
                await hold_attitude(
                    sess.motion,
                    pitch_vel=float(request.get("pitch_vel", 0.0)),
                    seconds=seconds,
                    hz=hz,
                )
                response = {"ok": True}
            elif command == "release_attitude":
                await release_attitude(sess.motion, seconds=seconds, hz=hz)
                response = {"ok": True}
            else:
                response = {"ok": False, "error": f"unknown command: {command}"}
        except Exception as exc:
            response = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        response["elapsed_sec"] = round(time.monotonic() - started, 3)
        writer.write((json.dumps(response, sort_keys=True) + "\n").encode("utf-8"))
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle_client, args.listen_host, args.listen_port)
    async with server:
        await server.serve_forever()
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
