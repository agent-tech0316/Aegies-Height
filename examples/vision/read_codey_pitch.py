"""Command-line Codey Rocky pitch reader for the Raspberry Pi."""
from __future__ import annotations

import argparse
import json
import time

from codey_pitch import DEFAULT_BAUD, read_codey_pitch


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default=None, help="Usually /dev/ttyUSB0 or /dev/ttyACM0. Omit to auto-detect.")
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD)
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--timeout-sec", type=float, default=5.0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--zero-at-start", action="store_true", help="Use the first reading as 0 deg and print relative pitch.")
    parser.add_argument("--zero-deg", type=float, default=None, help="Known raw Codey standing pitch to subtract.")
    parser.add_argument("--interval-sec", type=float, default=0.2)
    return parser


def print_reading(reading: dict[str, object], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(reading, sort_keys=True), flush=True)
    else:
        print(
            f"pitch_deg={float(reading['pitch_deg']):.2f} "
            f"samples={reading['samples']} port={reading['port']}",
            flush=True,
        )


def main() -> None:
    args = build_parser().parse_args()
    print("Reading Codey pitch. Press Ctrl-C to stop.", flush=True)
    zero_deg = args.zero_deg
    while True:
        reading = read_codey_pitch(
            port=args.port,
            baud=args.baud,
            samples=args.samples,
            timeout_sec=args.timeout_sec,
        )
        if zero_deg is None and args.zero_at_start:
            zero_deg = float(reading["pitch_deg"])
            print(f"ZERO raw_pitch_deg={zero_deg:.2f}", flush=True)
        if zero_deg is not None:
            reading["zero_deg"] = zero_deg
            reading["relative_pitch_deg"] = float(reading["pitch_deg"]) - zero_deg
        print_reading(reading, as_json=args.json)
        if args.once:
            break
        time.sleep(max(0.0, args.interval_sec))


if __name__ == "__main__":
    main()
