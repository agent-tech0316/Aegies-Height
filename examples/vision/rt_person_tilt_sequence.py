#!/usr/bin/env python3
"""RT-triggered person centering and tilt capture sequence.

This script intentionally does not call damping or lie_down. It assumes the
robot should remain standing.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from height_calculator import (
    DEFAULT_MODEL,
    DEFAULT_RTSP_URL,
    PersonBox,
    capture_one_frame,
    detect_people_yolo,
    read_hcsr04_distance_cm,
    require_cv2_numpy,
)


@dataclass
class CaptureResult:
    raw_image: str
    annotated_image: str
    detections: int
    selected: dict[str, float] | None
    center_error_ratio: float | None
    in_big_box: bool
    centered: bool


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Wait for RT, center person, tilt up/down, and save images."
    )
    parser.add_argument("--rtsp-url", default=DEFAULT_RTSP_URL)
    parser.add_argument("--output-dir", default="human_height_runs/rt_tilt_sequence")
    parser.add_argument("--jpeg-quality", type=int, default=92)
    parser.add_argument("--yolo-model", default=DEFAULT_MODEL)
    parser.add_argument("--yolo-confidence", type=float, default=0.35)
    parser.add_argument("--yolo-nms", type=float, default=0.45)
    parser.add_argument("--yolo-image-size", type=int, default=640)
    parser.add_argument("--person-index", type=int, default=0)

    parser.add_argument("--rt-port", type=int, default=45045)
    parser.add_argument("--trigger-once", action="store_true")
    parser.add_argument("--trigger-cooldown-sec", type=float, default=2.0)
    parser.add_argument("--max-triggers", type=int, default=0, help="0 means forever.")

    parser.add_argument("--robot-target", default="D1-demo")
    parser.add_argument("--robot-host", default="192.168.234.1")
    parser.add_argument("--robot-variant", default="zsl-1")
    parser.add_argument(
        "--motion-backend",
        choices=["remote-robot", "local-ff-sdk", "dry-run"],
        default="remote-robot",
        help="remote-robot runs motion on the robot through a tiny TCP motion server.",
    )
    parser.add_argument("--robot-motion-port", type=int, default=45100)
    parser.add_argument("--robot-exec-helper", default="scripts/robot_exec_pexpect.py")
    parser.add_argument(
        "--robot-motion-server",
        default="/home/firefly/Aegies-Height/scripts/robot_motion_server.py",
    )
    parser.add_argument("--start-robot-motion-server", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--dry-run-motion", action="store_true")
    parser.add_argument("--close-session-on-exit", action="store_true")
    parser.add_argument("--stand-at-start", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--stand-wait-sec", type=float, default=5.0)
    parser.add_argument("--stand-at-end", action=argparse.BooleanOptionalAction, default=False)

    parser.add_argument("--big-box-ratio", type=float, default=0.32)
    parser.add_argument("--center-tolerance-ratio", type=float, default=0.08)
    parser.add_argument("--center-method", choices=["lateral", "yaw"], default="lateral")
    parser.add_argument("--center-max-steps", type=int, default=6)
    parser.add_argument("--center-pulse-sec", type=float, default=0.35)
    parser.add_argument("--center-settle-sec", type=float, default=0.8)
    parser.add_argument("--center-lateral-speed", type=float, default=0.08)
    parser.add_argument("--center-yaw-speed", type=float, default=0.12)
    parser.add_argument("--invert-lateral", action="store_true")
    parser.add_argument("--invert-yaw", action="store_true")
    parser.add_argument("--worse-margin-ratio", type=float, default=0.02)

    parser.add_argument("--up-pitch-vel", type=float, default=0.30)
    parser.add_argument("--up-sec", type=float, default=1.2)
    parser.add_argument("--down-pitch-vel", type=float, default=-0.30)
    parser.add_argument("--down-sec", type=float, default=2.4)
    parser.add_argument("--return-up-sec", type=float, default=1.2)
    parser.add_argument("--tilt-hz", type=float, default=20.0)
    parser.add_argument("--tilt-pause-sec", type=float, default=1.5)
    parser.add_argument("--tilt-settle-sec", type=float, default=1.0)

    parser.add_argument("--hcsr04", action="store_true")
    parser.add_argument("--hcsr04-trigger-pin", type=int, default=17)
    parser.add_argument("--hcsr04-echo-pin", type=int, default=27)
    parser.add_argument("--hcsr04-samples", type=int, default=5)
    parser.add_argument("--hcsr04-sample-delay-sec", type=float, default=0.06)
    parser.add_argument("--hcsr04-max-distance-cm", type=float, default=400.0)
    parser.add_argument("--learn-background", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--background-learn-sec", type=float, default=3.0)

    return parser


def selected_to_dict(person: PersonBox | None) -> dict[str, float] | None:
    if person is None:
        return None
    return {
        "x": float(person.x),
        "y": float(person.y),
        "width": float(person.width),
        "height": float(person.height),
        "score": float(person.score),
        "center_x": float(person.center_x),
        "top_y": float(person.top_y),
        "bottom_y": float(person.bottom_y),
    }


def event_is_rt_trigger(payload: str) -> bool:
    text = payload.strip()
    if not text:
        return False
    try:
        data: Any = json.loads(text)
    except json.JSONDecodeError:
        upper = text.upper()
        return "RT" in upper and not any(word in upper for word in ("UP_FALSE", "RELEASED"))

    if not isinstance(data, dict):
        return False

    labels = [
        data.get("button"),
        data.get("label"),
        data.get("name"),
        data.get("control"),
    ]
    has_rt = any(str(label).upper() == "RT" for label in labels if label is not None)
    has_rt = has_rt or bool(data.get("RT")) or bool(data.get("rt"))
    if not has_rt:
        return False

    for key in ("pressed", "is_pressed", "down", "active"):
        if key in data and data[key] is False:
            return False
    if str(data.get("state", "")).lower() in {"up", "released", "false", "0"}:
        return False
    return True


def open_rt_socket(port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", port))
    sock.setblocking(False)
    return sock


async def wait_for_rt(sock: socket.socket, args: argparse.Namespace, last_trigger: float) -> float:
    print(f"WAITING_FOR_RT port={args.rt_port}", flush=True)
    while True:
        try:
            packet, addr = sock.recvfrom(4096)
        except BlockingIOError:
            await asyncio.sleep(0.05)
            continue
        payload = packet.decode("utf-8", errors="replace")
        now = time.monotonic()
        if now - last_trigger < args.trigger_cooldown_sec:
            continue
        if event_is_rt_trigger(payload):
            print(f"RT_TRIGGER from={addr} payload={payload.strip()}", flush=True)
            return now


async def connect_robot(args: argparse.Namespace):
    if args.dry_run_motion or args.motion_backend in {"dry-run", "remote-robot"}:
        print("DRY_RUN_MOTION robot connection skipped", flush=True)
        return None

    os.environ["FF_SDK_D1_HOST"] = args.robot_host
    os.environ["FF_SDK_D1_VARIANT"] = args.robot_variant

    import ff_sdk
    from ff_sdk import Config

    config = Config.from_env()
    extra = getattr(config, "extra", None)
    if isinstance(extra, dict):
        extra["d1_host"] = args.robot_host
        extra["d1_variant"] = args.robot_variant
    return await ff_sdk.connect(args.robot_target, config=config)


def robot_server_command(args: argparse.Namespace) -> str:
    return (
        "mkdir -p /home/firefly/Aegies-Height/logs; "
        "if pgrep -f '[r]obot_motion_server.py' >/dev/null; then "
        "echo ROBOT_MOTION_SERVER_ALREADY_RUNNING; "
        "else "
        "nohup python3 "
        f"{shlex_quote(args.robot_motion_server)} "
        f"--listen-port {int(args.robot_motion_port)} "
        f"--target {shlex_quote(args.robot_target)} "
        f"--robot-host {shlex_quote(args.robot_host)} "
        f"--robot-variant {shlex_quote(args.robot_variant)} "
        "> /home/firefly/Aegies-Height/logs/robot_motion_server.log 2>&1 & "
        "fi; "
        "sleep 2; "
        "tail -n 40 /home/firefly/Aegies-Height/logs/robot_motion_server.log 2>/dev/null || true"
    )


def shlex_quote(value: object) -> str:
    import shlex

    return shlex.quote(str(value))


def run_robot_ssh(args: argparse.Namespace, command: str, *, timeout: float = 30.0) -> str:
    helper = Path(args.robot_exec_helper)
    proc = subprocess.run(
        [sys.executable, str(helper), "--timeout", str(timeout), "--stdin-command"],
        input=command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"robot ssh failed rc={proc.returncode}: {proc.stdout}")
    return proc.stdout


async def ensure_remote_robot_motion_server(args: argparse.Namespace) -> None:
    if args.motion_backend != "remote-robot" or not args.start_robot_motion_server:
        return
    print("START_REMOTE_ROBOT_MOTION_SERVER", flush=True)
    output = await asyncio.to_thread(run_robot_ssh, args, robot_server_command(args), timeout=45.0)
    print(output.strip(), flush=True)
    ping = await remote_motion_command(args, {"cmd": "ping"}, timeout=8.0)
    print(f"REMOTE_MOTION_PING {ping}", flush=True)


async def remote_motion_command(
    args: argparse.Namespace,
    payload: dict[str, Any],
    *,
    timeout: float = 15.0,
) -> dict[str, Any]:
    def send() -> dict[str, Any]:
        with socket.create_connection((args.robot_host, args.robot_motion_port), timeout=timeout) as sock:
            sock.sendall((json.dumps(payload, sort_keys=True) + "\n").encode("utf-8"))
            sock.settimeout(timeout)
            data = b""
            while not data.endswith(b"\n"):
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
        if not data:
            raise RuntimeError("empty response from robot motion server")
        response = json.loads(data.decode("utf-8", errors="replace"))
        if not response.get("ok"):
            raise RuntimeError(str(response))
        return response

    return await asyncio.to_thread(send)


async def hold_attitude(sess, *, pitch_vel: float, seconds: float, hz: float) -> None:
    interval = 1.0 / hz
    loops = max(1, int(round(seconds * hz)))
    for _ in range(loops):
        await sess.motion.attitude_control(pitch_vel=pitch_vel)
        await asyncio.sleep(interval)


async def release_attitude(sess, *, seconds: float, hz: float) -> None:
    interval = 1.0 / hz
    loops = max(1, int(round(seconds * hz)))
    for _ in range(loops):
        await sess.motion.attitude_control()
        await asyncio.sleep(interval)


async def send_velocity(
    sess,
    *,
    linear: float = 0.0,
    lateral: float = 0.0,
    angular: float = 0.0,
    seconds: float,
    hz: float = 10.0,
) -> None:
    interval = 1.0 / hz
    loops = max(1, int(round(seconds * hz)))
    for _ in range(loops):
        await sess.motion.cmd_vel(linear=linear, lateral=lateral, angular=angular)
        await asyncio.sleep(interval)
    for _ in range(3):
        await sess.motion.cmd_vel(linear=0.0, lateral=0.0, angular=0.0)
        await asyncio.sleep(interval)


async def motion_hold_attitude(
    args: argparse.Namespace,
    sess,
    *,
    pitch_vel: float,
    seconds: float,
    hz: float,
) -> None:
    if args.dry_run_motion or args.motion_backend == "dry-run":
        print(f"DRY_ATTITUDE pitch_vel={pitch_vel} seconds={seconds}", flush=True)
    elif args.motion_backend == "remote-robot":
        await remote_motion_command(
            args,
            {"cmd": "attitude_hold", "pitch_vel": pitch_vel, "seconds": seconds, "hz": hz},
            timeout=max(8.0, seconds + 8.0),
        )
    else:
        await hold_attitude(sess, pitch_vel=pitch_vel, seconds=seconds, hz=hz)


async def motion_release_attitude(args: argparse.Namespace, sess, *, seconds: float, hz: float) -> None:
    if args.dry_run_motion or args.motion_backend == "dry-run":
        print(f"DRY_RELEASE_ATTITUDE seconds={seconds}", flush=True)
    elif args.motion_backend == "remote-robot":
        await remote_motion_command(
            args,
            {"cmd": "release_attitude", "seconds": seconds, "hz": hz},
            timeout=max(8.0, seconds + 8.0),
        )
    else:
        await release_attitude(sess, seconds=seconds, hz=hz)


async def motion_send_velocity(
    args: argparse.Namespace,
    sess,
    *,
    linear: float = 0.0,
    lateral: float = 0.0,
    angular: float = 0.0,
    seconds: float,
    hz: float = 10.0,
) -> None:
    if args.dry_run_motion or args.motion_backend == "dry-run":
        print(
            f"DRY_VELOCITY linear={linear} lateral={lateral} angular={angular} seconds={seconds}",
            flush=True,
        )
    elif args.motion_backend == "remote-robot":
        await remote_motion_command(
            args,
            {
                "cmd": "velocity_hold",
                "linear": linear,
                "lateral": lateral,
                "angular": angular,
                "seconds": seconds,
                "hz": hz,
            },
            timeout=max(8.0, seconds + 8.0),
        )
        await remote_motion_command(
            args,
            {"cmd": "zero_velocity", "seconds": 0.2, "hz": hz},
            timeout=8.0,
        )
    else:
        await send_velocity(
            sess,
            linear=linear,
            lateral=lateral,
            angular=angular,
            seconds=seconds,
            hz=hz,
        )


async def motion_stand(args: argparse.Namespace, sess) -> None:
    if args.dry_run_motion or args.motion_backend == "dry-run":
        print("DRY_STAND", flush=True)
    elif args.motion_backend == "remote-robot":
        await remote_motion_command(args, {"cmd": "stand"}, timeout=12.0)
    else:
        await sess.motion.stand()


def annotate_capture(
    *,
    raw_image: Path,
    annotated_image: Path,
    detections: list[PersonBox],
    selected: PersonBox | None,
    message: str,
    args: argparse.Namespace,
) -> CaptureResult:
    cv2, _np = require_cv2_numpy()
    image = cv2.imread(str(raw_image))
    if image is None:
        raise RuntimeError(f"Could not read captured image: {raw_image}")

    height, width = image.shape[:2]
    big_left = int(round(width * (0.5 - args.big_box_ratio)))
    big_right = int(round(width * (0.5 + args.big_box_ratio)))
    center_left = int(round(width * (0.5 - args.center_tolerance_ratio)))
    center_right = int(round(width * (0.5 + args.center_tolerance_ratio)))

    cv2.line(image, (big_left, 0), (big_left, height - 1), (0, 255, 255), 2)
    cv2.line(image, (big_right, 0), (big_right, height - 1), (0, 255, 255), 2)
    cv2.line(image, (center_left, 0), (center_left, height - 1), (255, 255, 0), 1)
    cv2.line(image, (center_right, 0), (center_right, height - 1), (255, 255, 0), 1)

    for index, person in enumerate(detections):
        is_selected = selected is not None and person is selected
        color = (0, 255, 0) if is_selected else (0, 0, 255)
        x1, y1 = int(person.x), int(person.y)
        x2, y2 = int(person.x + person.width), int(person.y + person.height)
        cv2.rectangle(image, (x1, y1), (x2, y2), color, 3 if is_selected else 2)
        cv2.putText(
            image,
            f"person {index} {person.score:.2f}",
            (x1, max(25, y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            color,
            2,
            cv2.LINE_AA,
        )

    cv2.rectangle(image, (0, 0), (width - 1, 42), (0, 0, 0), -1)
    cv2.putText(
        image,
        message,
        (12, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (0, 0, 255),
        2,
        cv2.LINE_AA,
    )
    cv2.imwrite(str(annotated_image), image)

    center_error_ratio = None
    in_big_box = False
    centered = False
    if selected is not None:
        center_error_ratio = (selected.center_x - (width / 2.0)) / width
        in_big_box = abs(center_error_ratio) <= args.big_box_ratio
        centered = abs(center_error_ratio) <= args.center_tolerance_ratio

    return CaptureResult(
        raw_image=str(raw_image),
        annotated_image=str(annotated_image),
        detections=len(detections),
        selected=selected_to_dict(selected),
        center_error_ratio=center_error_ratio,
        in_big_box=in_big_box,
        centered=centered,
    )


def capture_and_detect(
    args: argparse.Namespace,
    *,
    trigger_index: int,
    label: str,
    attempt: int,
    message: str,
) -> CaptureResult:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"rt_tilt_{trigger_index:03d}_{attempt:02d}_{label}"
    raw_image = output_dir / f"{stem}.jpg"
    annotated_image = output_dir / f"{stem}_annotated.jpg"

    capture_one_frame(
        rtsp_url=args.rtsp_url,
        output=raw_image,
        jpeg_quality=args.jpeg_quality,
    )
    detections = detect_people_yolo(
        str(raw_image),
        model_path=Path(args.yolo_model),
        confidence_threshold=args.yolo_confidence,
        nms_threshold=args.yolo_nms,
        image_size=args.yolo_image_size,
    )
    selected = detections[args.person_index] if len(detections) > args.person_index else None
    result = annotate_capture(
        raw_image=raw_image,
        annotated_image=annotated_image,
        detections=detections,
        selected=selected,
        message=message,
        args=args,
    )
    print(
        "CAPTURE "
        f"label={label} detections={result.detections} "
        f"center_error={result.center_error_ratio} "
        f"in_big_box={result.in_big_box} centered={result.centered} "
        f"image={result.annotated_image}",
        flush=True,
    )
    return result


async def center_person(args: argparse.Namespace, sess, trigger_index: int) -> tuple[CaptureResult, bool]:
    direction_multiplier = 1.0
    previous_error_abs: float | None = None
    latest: CaptureResult | None = None

    for attempt in range(args.center_max_steps + 1):
        latest = capture_and_detect(
            args,
            trigger_index=trigger_index,
            label=f"center_attempt_{attempt}",
            attempt=attempt,
            message="RT sequence: looking for person",
        )

        if latest.selected is None:
            print("NO_PERSON_DETECTED waiting for next RT", flush=True)
            return latest, False
        if latest.center_error_ratio is None:
            return latest, False
        if not latest.in_big_box:
            print(
                f"PERSON_OUTSIDE_BIG_BOX center_error={latest.center_error_ratio:.3f}",
                flush=True,
            )
            return latest, False
        if latest.centered:
            print("PERSON_CENTERED", flush=True)
            return latest, True
        if attempt >= args.center_max_steps:
            print("PERSON_NOT_CENTERED_AFTER_MAX_STEPS", flush=True)
            return latest, False

        current_error_abs = abs(latest.center_error_ratio)
        if (
            previous_error_abs is not None
            and current_error_abs > previous_error_abs + args.worse_margin_ratio
        ):
            direction_multiplier *= -1.0
            print("CENTER_MOVE_WORSENED flipping direction", flush=True)

        base_direction = -1.0 if latest.center_error_ratio < 0.0 else 1.0
        move_direction = base_direction * direction_multiplier

        if args.dry_run_motion:
            print(f"DRY_CENTER_MOVE method={args.center_method} direction={move_direction}", flush=True)
        elif args.center_method == "lateral":
            lateral = move_direction * args.center_lateral_speed
            if args.invert_lateral:
                lateral *= -1.0
            print(f"CENTER_MOVE lateral={lateral:.3f} seconds={args.center_pulse_sec}", flush=True)
            await motion_send_velocity(args, sess, lateral=lateral, seconds=args.center_pulse_sec)
        else:
            angular = move_direction * args.center_yaw_speed
            if args.invert_yaw:
                angular *= -1.0
            print(f"CENTER_MOVE yaw={angular:.3f} seconds={args.center_pulse_sec}", flush=True)
            await motion_send_velocity(args, sess, angular=angular, seconds=args.center_pulse_sec)

        previous_error_abs = current_error_abs
        await asyncio.sleep(args.center_settle_sec)

    assert latest is not None
    return latest, False


async def tilt_sequence(args: argparse.Namespace, sess, trigger_index: int) -> dict[str, Any]:
    captures: dict[str, CaptureResult] = {}

    print("TILT_UP", flush=True)
    if args.dry_run_motion:
        print(f"DRY_TILT_UP pitch_vel={args.up_pitch_vel} sec={args.up_sec}", flush=True)
    else:
        await motion_hold_attitude(args, sess, pitch_vel=args.up_pitch_vel, seconds=args.up_sec, hz=args.tilt_hz)
        await motion_release_attitude(args, sess, seconds=args.tilt_pause_sec, hz=args.tilt_hz)
    await asyncio.sleep(args.tilt_settle_sec)
    captures["up"] = capture_and_detect(
        args,
        trigger_index=trigger_index,
        label="tilt_up",
        attempt=90,
        message="tilt up capture",
    )

    print("TILT_DOWN", flush=True)
    if args.dry_run_motion:
        print(f"DRY_TILT_DOWN pitch_vel={args.down_pitch_vel} sec={args.down_sec}", flush=True)
    else:
        await motion_hold_attitude(args, sess, pitch_vel=args.down_pitch_vel, seconds=args.down_sec, hz=args.tilt_hz)
        await motion_release_attitude(args, sess, seconds=args.tilt_pause_sec, hz=args.tilt_hz)
    await asyncio.sleep(args.tilt_settle_sec)
    captures["down"] = capture_and_detect(
        args,
        trigger_index=trigger_index,
        label="tilt_down",
        attempt=91,
        message="tilt down capture",
    )

    print("RETURN_NEUTRAL_STANDING", flush=True)
    if args.dry_run_motion:
        print(f"DRY_RETURN_UP pitch_vel={abs(args.up_pitch_vel)} sec={args.return_up_sec}", flush=True)
    else:
        if args.return_up_sec > 0.0:
            await motion_hold_attitude(
                args,
                sess,
                pitch_vel=abs(args.up_pitch_vel),
                seconds=args.return_up_sec,
                hz=args.tilt_hz,
            )
        await motion_release_attitude(args, sess, seconds=args.tilt_pause_sec, hz=args.tilt_hz)
        if args.stand_at_end:
            await motion_stand(args, sess)
            await asyncio.sleep(args.stand_wait_sec)

    captures["final"] = capture_and_detect(
        args,
        trigger_index=trigger_index,
        label="final_neutral",
        attempt=92,
        message="final neutral standing",
    )
    return {key: result.__dict__ for key, result in captures.items()}


def learn_background_if_requested(args: argparse.Namespace) -> float | None:
    if not (args.hcsr04 and args.learn_background):
        return None
    deadline = time.monotonic() + args.background_learn_sec
    readings: list[float] = []
    print(
        f"LEARNING_BACKGROUND keep empty/wall space in front of sensor for {args.background_learn_sec:.1f}s",
        flush=True,
    )
    while time.monotonic() < deadline:
        reading = read_hcsr04_distance_cm(
            trigger_pin=args.hcsr04_trigger_pin,
            echo_pin=args.hcsr04_echo_pin,
            samples=args.hcsr04_samples,
            sample_delay_sec=args.hcsr04_sample_delay_sec,
            max_distance_cm=args.hcsr04_max_distance_cm,
        )
        readings.append(float(reading))
    readings.sort()
    background = readings[len(readings) // 2] if readings else None
    print(f"BACKGROUND_LEARNED distance_cm={background}", flush=True)
    return background


async def handle_trigger(args: argparse.Namespace, sess, trigger_index: int) -> dict[str, Any]:
    centered_capture, centered = await center_person(args, sess, trigger_index)
    result: dict[str, Any] = {
        "trigger_index": trigger_index,
        "centered": centered,
        "center_capture": centered_capture.__dict__,
    }
    if not centered:
        result["status"] = "not_centered_or_no_person"
        return result

    result["status"] = "centered_tilt_sequence_started"
    result["tilt_captures"] = await tilt_sequence(args, sess, trigger_index)
    result["status"] = "done"
    return result


async def main_async() -> int:
    args = build_parser().parse_args()
    Path(args.output_dir).mkdir(parents=True, exist_ok=True)
    log_path = Path(args.output_dir) / "rt_person_tilt_sequence.jsonl"

    background = learn_background_if_requested(args)
    await ensure_remote_robot_motion_server(args)
    sess = await connect_robot(args)
    sock = None if args.trigger_once else open_rt_socket(args.rt_port)
    last_trigger = 0.0
    trigger_index = 0

    try:
        if args.stand_at_start:
            print("STAND_AT_START", flush=True)
            await motion_stand(args, sess)
            await asyncio.sleep(args.stand_wait_sec)

        while args.max_triggers == 0 or trigger_index < args.max_triggers:
            if args.trigger_once:
                if trigger_index > 0:
                    break
                print("TRIGGER_ONCE", flush=True)
            else:
                assert sock is not None
                last_trigger = await wait_for_rt(sock, args, last_trigger)

            trigger_index += 1
            result = await handle_trigger(args, sess, trigger_index)
            result["background_distance_cm"] = background
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(result, sort_keys=True) + "\n")
            print(f"SEQUENCE_RESULT status={result['status']} log={log_path}", flush=True)

            if args.trigger_once:
                break
    finally:
        if sock is not None:
            sock.close()
        if sess is not None:
            try:
                await motion_release_attitude(args, sess, seconds=0.3, hz=args.tilt_hz)
                await motion_send_velocity(args, sess, seconds=0.2)
            except Exception as exc:
                print(f"WARN neutral cleanup failed: {exc}", flush=True)
            if args.close_session_on_exit:
                await sess.close()
                print("SESSION_CLOSED", flush=True)
            else:
                print("LEAVE_SESSION_OPEN_NO_DAMPING", flush=True)
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
