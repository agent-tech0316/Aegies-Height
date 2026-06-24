#!/usr/bin/env python3
"""Copy one file from the Raspberry Pi to the robot using password scp."""

from __future__ import annotations

import argparse
import os
import shlex
import sys

import pexpect


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("destination")
    parser.add_argument("--host", default="192.168.234.1")
    parser.add_argument("--user", default="firefly")
    parser.add_argument("--password", default=os.environ.get("ROBOT_PASSWORD"))
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()

    if args.password is None:
        print("ERROR: set ROBOT_PASSWORD or pass --password", file=sys.stderr)
        return 2

    command = (
        "scp "
        "-o StrictHostKeyChecking=accept-new "
        "-o UserKnownHostsFile=/home/agent-tech/.ssh/known_hosts "
        f"{shlex.quote(args.source)} "
        f"{shlex.quote(args.user)}@{shlex.quote(args.host)}:{shlex.quote(args.destination)}"
    )
    child = pexpect.spawn(command, encoding="utf-8", timeout=args.timeout)
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
            print("\nERROR: timed out waiting for robot scp", file=sys.stderr)
            child.close(force=True)
            return 124

    child.close()
    return child.exitstatus if child.exitstatus is not None else 0


if __name__ == "__main__":
    raise SystemExit(main())
