#!/usr/bin/env python3
"""Small phone-friendly dashboard for the Pi height system.

Run on the Raspberry Pi, then open http://<pi-ip>:8000 from a phone on the
same network. This dashboard intentionally uses only the Python standard
library so it can run offline.
"""

from __future__ import annotations

import argparse
import html
import json
import mimetypes
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import parse_qs, quote, unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]


class RunningProcess:
    def __init__(self, name: str, command: list[str], log_path: Path):
        self.name = name
        self.command = command
        self.log_path = log_path
        self.started_at = time.time()
        self.proc = subprocess.Popen(
            command,
            cwd=str(ROOT),
            stdout=log_path.open("ab"),
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )

    @property
    def running(self) -> bool:
        return self.proc.poll() is None

    def stop(self) -> None:
        if not self.running:
            return
        try:
            if os.name == "nt":
                self.proc.terminate()
            else:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
            self.proc.wait(timeout=4)
        except Exception:
            if os.name == "nt":
                self.proc.kill()
            else:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)


class ProcessManager:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.lock = threading.Lock()
        self.procs: dict[str, RunningProcess] = {}
        self.logs_dir = ROOT / "dashboard_logs"
        self.logs_dir.mkdir(exist_ok=True)
        self.message = "Dashboard ready."

    def command_height_live(self, *, once: bool, auto_tilt: str) -> list[str]:
        cmd = [
            self.args.python,
            "examples/vision/human_height_live.py",
            "--rtsp-url",
            self.args.rtsp_url,
            "--camera-calibration",
            self.args.camera_calibration,
            "--output-dir",
            self.args.output_dir,
            "--interval-sec",
            str(self.args.interval_sec),
            "--hcsr04",
            "--depth-sensor-behind-camera-cm",
            str(self.args.depth_sensor_behind_camera_cm),
            "--human-depth-bursts",
            str(self.args.human_depth_bursts),
            "--auto-tilt",
            auto_tilt,
            "--robot-host",
            self.args.robot_host,
            "--robot-variant",
            self.args.robot_variant,
            "--center-tolerance-ratio",
            str(self.args.center_tolerance_ratio),
        ]
        if self.args.codey_pitch:
            cmd.append("--codey-pitch")
            if self.args.codey_port:
                cmd.extend(["--codey-port", self.args.codey_port])
        if once:
            cmd.append("--once")
        return cmd

    def command_rt_wait(self) -> list[str]:
        return [
            self.args.python,
            "examples/vision/rt_person_tilt_sequence.py",
            "--rtsp-url",
            self.args.rtsp_url,
            "--output-dir",
            self.args.rt_output_dir,
            "--motion-backend",
            self.args.motion_backend,
            "--robot-host",
            self.args.robot_host,
            "--robot-variant",
            self.args.robot_variant,
            "--rt-port",
            str(self.args.rt_port),
            "--big-box-ratio",
            str(self.args.big_box_ratio),
            "--center-tolerance-ratio",
            str(self.args.rt_center_tolerance_ratio),
            "--up-sec",
            str(self.args.up_sec),
            "--down-sec",
            str(self.args.down_sec),
            "--tilt-pause-sec",
            str(self.args.tilt_pause_sec),
            "--no-stand-at-start",
            "--no-stand-at-end",
        ]

    def start(self, name: str, command_factory: Callable[[], list[str]]) -> None:
        with self.lock:
            old = self.procs.get(name)
            if old and old.running:
                self.message = f"{name} is already running."
                return
            log_path = self.logs_dir / f"{name}.log"
            command = command_factory()
            log_path.write_text(
                f"$ {' '.join(command)}\n\n",
                encoding="utf-8",
            )
            self.procs[name] = RunningProcess(name, command, log_path)
            self.message = f"Started {name}."

    def stop(self, name: str | None = None) -> None:
        with self.lock:
            targets = list(self.procs.items()) if name is None else [(name, self.procs.get(name))]
            for proc_name, item in targets:
                if item is not None:
                    item.stop()
                    self.message = f"Stopped {proc_name}."
            if name is None:
                self.message = "Stopped all dashboard-started processes."

    def state(self) -> dict[str, object]:
        with self.lock:
            procs = {}
            for name, item in self.procs.items():
                procs[name] = {
                    "running": item.running,
                    "pid": item.proc.pid,
                    "started_at": item.started_at,
                    "log_path": str(item.log_path.relative_to(ROOT)),
                    "returncode": item.proc.poll(),
                }
            return {"message": self.message, "processes": procs}


def latest_image(root: Path) -> Path | None:
    patterns = [
        "*_annotated.jpg",
        "*annotated*.jpg",
        "*.jpg",
        "*.png",
    ]
    candidates: list[Path] = []
    for pattern in patterns:
        candidates.extend(path for path in root.glob(pattern) if path.is_file())
        if candidates:
            break
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def tail_text(path: Path, max_chars: int = 5000) -> str:
    if not path.exists():
        return ""
    data = path.read_bytes()
    return data[-max_chars:].decode("utf-8", errors="replace")


def latest_jsonl(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    lines = [line for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
    if not lines:
        return None
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError:
        return {"raw": lines[-1]}


def make_handler(manager: ProcessManager):
    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self.send_html(self.render_index())
                return
            if parsed.path == "/state.json":
                self.send_json(self.build_state())
                return
            if parsed.path == "/latest-image":
                query = parse_qs(parsed.query)
                kind = query.get("kind", ["height"])[0]
                root = ROOT / (manager.args.rt_output_dir if kind == "rt" else manager.args.output_dir)
                image = latest_image(root)
                if image is None:
                    self.send_error(404, "No image yet")
                    return
                self.send_file(image)
                return
            if parsed.path.startswith("/file/"):
                rel = unquote(parsed.path[len("/file/") :])
                path = (ROOT / rel).resolve()
                if not str(path).startswith(str(ROOT.resolve())) or not path.is_file():
                    self.send_error(404, "File not found")
                    return
                self.send_file(path)
                return
            self.send_error(404, "Not found")

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            action = parsed.path.strip("/")
            if action == "start-watch":
                manager.start("height_watch", lambda: manager.command_height_live(once=False, auto_tilt="none"))
            elif action == "start-height-auto":
                manager.start("height_auto", lambda: manager.command_height_live(once=False, auto_tilt="baseline"))
            elif action == "run-once":
                manager.start("height_once", lambda: manager.command_height_live(once=True, auto_tilt="none"))
            elif action == "start-rt-wait":
                manager.start("rt_wait", manager.command_rt_wait)
            elif action == "stop-all":
                manager.stop(None)
            elif action.startswith("stop/"):
                manager.stop(action.split("/", 1)[1])
            else:
                self.send_error(404, "Unknown action")
                return
            self.send_response(303)
            self.send_header("Location", "/")
            self.end_headers()

        def build_state(self) -> dict[str, object]:
            output_dir = ROOT / manager.args.output_dir
            rt_dir = ROOT / manager.args.rt_output_dir
            state = manager.state()
            state["height_result"] = latest_jsonl(output_dir / "human_height_results.jsonl")
            state["rt_result"] = latest_jsonl(rt_dir / "rt_person_tilt_sequence.jsonl")
            state["display_message"] = tail_text(output_dir / "display_message.txt", max_chars=1000)
            return state

        def render_index(self) -> str:
            state = self.build_state()
            height_result = state.get("height_result") or {}
            rt_result = state.get("rt_result") or {}
            display_message = str(state.get("display_message") or "")
            processes = state.get("processes") or {}
            process_rows = []
            if isinstance(processes, dict):
                for name, info in processes.items():
                    running = bool(info.get("running")) if isinstance(info, dict) else False
                    log_path = str(info.get("log_path")) if isinstance(info, dict) else ""
                    process_rows.append(
                        f"<tr><td>{html.escape(name)}</td><td>{'running' if running else 'stopped'}</td>"
                        f"<td><a href='/file/{quote(log_path)}'>{html.escape(log_path)}</a></td></tr>"
                    )
            if not process_rows:
                process_rows.append("<tr><td colspan='3'>No dashboard-started processes.</td></tr>")

            return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="2">
  <title>Aegies Height Dashboard</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 16px; background: #101418; color: #f2f5f7; }}
    h1 {{ font-size: 22px; }}
    h2 {{ font-size: 17px; margin-top: 22px; }}
    button {{ font-size: 16px; padding: 12px 14px; margin: 5px; border: 0; border-radius: 8px; }}
    .start {{ background: #20c997; color: #08110e; }}
    .warn {{ background: #ffd166; color: #16120b; }}
    .stop {{ background: #ff5d5d; color: #180808; }}
    .card {{ background: #18202a; padding: 12px; border-radius: 10px; margin-bottom: 14px; }}
    img {{ width: 100%; max-width: 1100px; border: 1px solid #303945; background: #000; }}
    pre {{ white-space: pre-wrap; overflow-wrap: anywhere; background: #0b0f13; padding: 10px; border-radius: 8px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    td, th {{ border-bottom: 1px solid #303945; padding: 8px; text-align: left; }}
    a {{ color: #8ecae6; }}
  </style>
</head>
<body>
  <h1>Aegies Height Dashboard</h1>
  <div class="card"><strong>Status:</strong> {html.escape(str(state.get("message", "")))}</div>

  <div class="card">
    <form method="post" action="/start-watch"><button class="start">Start Watch Only</button></form>
    <form method="post" action="/start-height-auto"><button class="warn">Start Height Auto Tilt</button></form>
    <form method="post" action="/run-once"><button>Run One Frame</button></form>
    <form method="post" action="/start-rt-wait"><button class="start">Wait For RT Tilt</button></form>
    <form method="post" action="/stop-all"><button class="stop">Stop All</button></form>
  </div>

  <h2>Latest Height Image</h2>
  <img src="/latest-image?kind=height&t={time.time()}" alt="latest height image">

  <h2>Latest RT Tilt Image</h2>
  <img src="/latest-image?kind=rt&t={time.time()}" alt="latest rt image">

  <h2>Display Message</h2>
  <pre>{html.escape(display_message)}</pre>

  <h2>Latest Height Result</h2>
  <pre>{html.escape(json.dumps(height_result, indent=2, sort_keys=True))}</pre>

  <h2>Latest RT Result</h2>
  <pre>{html.escape(json.dumps(rt_result, indent=2, sort_keys=True))}</pre>

  <h2>Processes</h2>
  <table><tr><th>Name</th><th>Status</th><th>Log</th></tr>{''.join(process_rows)}</table>
</body>
</html>"""

        def send_html(self, body: str) -> None:
            data = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def send_json(self, obj: object) -> None:
            data = json.dumps(obj, indent=2, sort_keys=True).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def send_file(self, path: Path) -> None:
            data = path.read_bytes()
            content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, fmt: str, *args: object) -> None:
            print(f"{self.address_string()} - {fmt % args}", flush=True)

    return DashboardHandler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--rtsp-url", default="rtsp://192.168.234.1:8554/test")
    parser.add_argument("--camera-calibration", default="calibrations/charuco_camera_calibration_refined.json")
    parser.add_argument("--output-dir", default="human_height_runs/latest")
    parser.add_argument("--rt-output-dir", default="human_height_runs/rt_tilt_sequence")
    parser.add_argument("--interval-sec", type=float, default=1.0)
    parser.add_argument("--depth-sensor-behind-camera-cm", type=float, default=15.0)
    parser.add_argument("--human-depth-bursts", type=int, default=5)
    parser.add_argument("--center-tolerance-ratio", type=float, default=0.16)
    parser.add_argument("--codey-pitch", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--codey-port", default="/dev/ttyUSB0")
    parser.add_argument("--robot-host", default="192.168.234.1")
    parser.add_argument("--robot-variant", default="zsl-1")
    parser.add_argument("--motion-backend", choices=["remote-robot", "local-ff-sdk", "dry-run"], default="remote-robot")
    parser.add_argument("--rt-port", type=int, default=45045)
    parser.add_argument("--big-box-ratio", type=float, default=0.32)
    parser.add_argument("--rt-center-tolerance-ratio", type=float, default=0.08)
    parser.add_argument("--up-sec", type=float, default=1.2)
    parser.add_argument("--down-sec", type=float, default=2.4)
    parser.add_argument("--tilt-pause-sec", type=float, default=1.5)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    manager = ProcessManager(args)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(manager))
    print(f"Dashboard running: http://{args.host}:{args.port}", flush=True)
    print("Open this from your phone using the Pi IP address.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping dashboard...", flush=True)
    finally:
        manager.stop(None)
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
