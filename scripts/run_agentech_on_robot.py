#!/usr/bin/env python3
"""Copy a student Agentech script to the robot and run it over SSH."""

from __future__ import annotations

import argparse
import os
import shlex
import sys
from pathlib import Path

import pexpect


def run_password_command(command: str, password: str, timeout: float) -> int:
    child = pexpect.spawn(command, encoding="utf-8", timeout=timeout)
    child.logfile_read = sys.stdout

    while True:
        index = child.expect(
            [
                "Are you sure you want to continue connecting",
                "[Pp]assword:",
                pexpect.EOF,
                pexpect.TIMEOUT,
            ]
        )
        if index == 0:
            child.sendline("yes")
        elif index == 1:
            child.sendline(password)
        elif index == 2:
            break
        else:
            print("\nERROR: timed out waiting for robot command", file=sys.stderr)
            child.close(force=True)
            return 124

    child.close()
    return child.exitstatus if child.exitstatus is not None else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload and run an Agentech Python script on the robot.")
    parser.add_argument("script", help="Local Python file, for example examples/student_forward.py")
    parser.add_argument("--host", default="192.168.234.1", help="Robot SSH host after connecting to the robot hotspot.")
    parser.add_argument("--user", default="firefly")
    parser.add_argument("--password", default=os.environ.get("ROBOT_PASSWORD"))
    parser.add_argument("--remote-path", default="/tmp/agentech_student.py")
    parser.add_argument("--remote-root", default="/tmp/agentech_runtime")
    parser.add_argument("--python", default="python3")
    parser.add_argument("--variant", default="zsl-1w")
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()

    script = Path(args.script)
    if not script.exists():
        print(f"ERROR: script not found: {script}", file=sys.stderr)
        return 2
    if args.password is None:
        print("ERROR: set ROBOT_PASSWORD or pass --password", file=sys.stderr)
        return 2

    ssh_options = "-o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/home/agent-tech/.ssh/known_hosts"
    repo_root = Path(__file__).resolve().parents[1]
    package_dir = repo_root / "agentech"
    if not package_dir.exists():
        print(f"ERROR: local agentech package not found: {package_dir}", file=sys.stderr)
        return 2

    remote_root = args.remote_root.rstrip("/")
    mkdir_command = f"mkdir -p {shlex.quote(remote_root)}"
    ssh_mkdir = f"ssh {ssh_options} {shlex.quote(args.user)}@{shlex.quote(args.host)} {shlex.quote(mkdir_command)}"
    mkdir_status = run_password_command(ssh_mkdir, args.password, args.timeout)
    if mkdir_status != 0:
        return mkdir_status

    package_destination = f"{args.user}@{args.host}:{remote_root}/"
    package_copy_command = f"scp -r {ssh_options} {shlex.quote(str(package_dir))} {shlex.quote(package_destination)}"
    package_copy_status = run_password_command(package_copy_command, args.password, args.timeout)
    if package_copy_status != 0:
        return package_copy_status

    destination = f"{args.user}@{args.host}:{args.remote_path}"
    copy_command = f"scp {ssh_options} {shlex.quote(str(script))} {shlex.quote(destination)}"
    copy_status = run_password_command(copy_command, args.password, args.timeout)
    if copy_status != 0:
        return copy_status

    remote_command = (
        f"export PYTHONPATH={shlex.quote(remote_root)}:${{PYTHONPATH:-}}; "
        f"export FF_SDK_D1_VARIANT={shlex.quote(args.variant)}; "
        "export FF_SDK_DRY_RUN=0; "
        f"{shlex.quote(args.python)} {shlex.quote(args.remote_path)}"
    )
    ssh_command = f"ssh {ssh_options} {shlex.quote(args.user)}@{shlex.quote(args.host)} {shlex.quote(remote_command)}"
    return run_password_command(ssh_command, args.password, args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
