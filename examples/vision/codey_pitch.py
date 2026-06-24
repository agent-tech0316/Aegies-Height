"""Read Codey Rocky pitch values from a USB serial connection.

Codey should run this mBlock-uploaded loop:

    import time
    import codey

    while True:
        print(codey.motion_sensor.get_pitch())
        time.sleep(1)
"""
from __future__ import annotations

import glob
import json
import os
import select
import statistics
import termios
import time
from pathlib import Path


DEFAULT_BAUD = 115200


def find_codey_port(preferred: str | None = None) -> str:
    if preferred:
        if Path(preferred).exists():
            return preferred
        raise FileNotFoundError(f"Codey serial port does not exist: {preferred}")

    candidates: list[str] = []
    for pattern in ("/dev/ttyUSB*", "/dev/ttyACM*"):
        candidates.extend(glob.glob(pattern))
    candidates = sorted(dict.fromkeys(candidates))
    if not candidates:
        raise FileNotFoundError("No Codey serial device found. Check: ls /dev/ttyUSB* /dev/ttyACM*")
    return candidates[0]


def _baud_constant(baud: int) -> int:
    name = f"B{baud}"
    if not hasattr(termios, name):
        raise ValueError(f"Unsupported baud rate for termios: {baud}")
    return int(getattr(termios, name))


def _configure_serial_fd(fd: int, baud: int) -> None:
    attrs = termios.tcgetattr(fd)
    baud_const = _baud_constant(baud)

    attrs[0] = 0
    attrs[1] = 0
    attrs[2] = termios.CLOCAL | termios.CREAD | termios.CS8
    attrs[3] = 0
    attrs[4] = baud_const
    attrs[5] = baud_const
    attrs[6][termios.VMIN] = 0
    attrs[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, attrs)
    termios.tcflush(fd, termios.TCIFLUSH)


def _parse_pitch_line(line: bytes) -> float | None:
    text = line.decode("utf-8", errors="replace").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def read_codey_pitch(
    *,
    port: str | None = None,
    baud: int = DEFAULT_BAUD,
    samples: int = 3,
    timeout_sec: float = 5.0,
) -> dict[str, object]:
    """Return a median pitch reading from Codey Rocky.

    This uses only Python standard-library serial handling, so it works from
    the Pi's custom Python used by ff_sdk without needing pyserial installed.
    """
    resolved_port = find_codey_port(port)
    sample_target = max(1, int(samples))
    deadline = time.monotonic() + max(0.2, float(timeout_sec))
    values: list[float] = []
    buffer = b""

    fd = os.open(resolved_port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        _configure_serial_fd(fd, baud)
        while time.monotonic() < deadline and len(values) < sample_target:
            wait_sec = max(0.0, min(0.2, deadline - time.monotonic()))
            readable, _, _ = select.select([fd], [], [], wait_sec)
            if not readable:
                continue
            chunk = os.read(fd, 1024)
            if not chunk:
                continue
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                value = _parse_pitch_line(line)
                if value is not None:
                    values.append(value)
                    if len(values) >= sample_target:
                        break
    finally:
        os.close(fd)

    if not values:
        raise TimeoutError(f"No pitch values read from {resolved_port} within {timeout_sec:.1f}s")

    return {
        "port": resolved_port,
        "baud": baud,
        "samples": values,
        "sample_count": len(values),
        "pitch_deg": float(statistics.median(values)),
        "mean_pitch_deg": float(statistics.fmean(values)),
    }


def dumps_reading(reading: dict[str, object]) -> str:
    return json.dumps(reading, sort_keys=True)
