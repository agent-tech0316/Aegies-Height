#!/usr/bin/env python3
"""Run one shell command on the robot through password SSH.

This is a small fallback for systems where sshpass is not installed. It is
intended to run on the Raspberry Pi, which can reach the robot network.
"""

from __future__ import annotations

import argparse
import os
import shlex
import sys

import pexpect


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="192.168.234.1")
    parser.add_argument("--user", default="firefly")
    parser.add_argument("--password", default=os.environ.get("ROBOT_PASSWORD"))
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument(
        "--stdin-command",
        action="store_true",
        help="Read the remote shell command from stdin instead of argv.",
    )
    parser.add_argument("command", nargs="*")
    args = parser.parse_args()

    if args.stdin_command:
        command = sys.stdin.read()
    else:
        command = " ".join(args.command)
    command = command.replace("\r\n", "\n").replace("\r", "\n")
    if not command.strip():
        print("ERROR: empty command", file=sys.stderr)
        return 2
    if args.password is None:
        print("ERROR: set ROBOT_PASSWORD or pass --password", file=sys.stderr)
        return 2
    ssh_command = (
        "ssh "
        "-o StrictHostKeyChecking=accept-new "
        "-o UserKnownHostsFile=/home/agent-tech/.ssh/known_hosts "
        f"{shlex.quote(args.user)}@{shlex.quote(args.host)} "
        f"{shlex.quote(command)}"
    )

    child = pexpect.spawn(ssh_command, encoding="utf-8", timeout=args.timeout)
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
            child.sendline(args.password)
        elif index == 2:
            break
        else:
            print("\nERROR: timed out waiting for robot SSH", file=sys.stderr)
            child.close(force=True)
            return 124

    child.close()
    return child.exitstatus if child.exitstatus is not None else 0


if __name__ == "__main__":
    raise SystemExit(main())
