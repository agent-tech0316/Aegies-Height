"""Read the Raspberry Pi HC-SR04 depth sensor.

Default wiring for this project:

    HC-SR04 trigger -> Raspberry Pi GPIO 17
    HC-SR04 echo    -> Raspberry Pi GPIO 27

Run on the Raspberry Pi:

    python3 examples/vision/read_depth_sensor.py

The HC-SR04 echo pin is a 5V signal. Use a voltage divider or level shifter so
the Raspberry Pi GPIO pin only sees 3.3V.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import time


DEFAULT_TRIGGER_PIN = 17
DEFAULT_ECHO_PIN = 27


def require_distance_sensor():
    try:
        from gpiozero import DistanceSensor
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "This script needs gpiozero on the Raspberry Pi. "
            "Install with: python3 -m pip install gpiozero"
        ) from exc
    return DistanceSensor


def read_distance_cm(sensor, *, samples: int, sample_delay_sec: float, max_distance_cm: float) -> float:
    distances: list[float] = []
    for _ in range(max(1, samples)):
        distance_cm = float(sensor.distance) * 100.0
        if math.isfinite(distance_cm) and 0.0 < distance_cm <= max_distance_cm:
            distances.append(distance_cm)
        time.sleep(max(0.0, sample_delay_sec))

    if not distances:
        raise RuntimeError("Depth sensor did not return a valid distance sample.")
    return float(statistics.median(distances))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trigger-pin", type=int, default=DEFAULT_TRIGGER_PIN)
    parser.add_argument("--echo-pin", type=int, default=DEFAULT_ECHO_PIN)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--sample-delay-sec", type=float, default=0.04)
    parser.add_argument("--interval-sec", type=float, default=0.2)
    parser.add_argument("--max-distance-cm", type=float, default=400.0)
    parser.add_argument("--once", action="store_true", help="Read once and exit.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of plain text.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    DistanceSensor = require_distance_sensor()
    sensor = DistanceSensor(
        trigger=args.trigger_pin,
        echo=args.echo_pin,
        max_distance=args.max_distance_cm / 100.0,
    )

    try:
        time.sleep(0.1)
        while True:
            distance_cm = read_distance_cm(
                sensor,
                samples=args.samples,
                sample_delay_sec=args.sample_delay_sec,
                max_distance_cm=args.max_distance_cm,
            )
            if args.json:
                print(
                    json.dumps(
                        {
                            "distance_cm": round(distance_cm, 1),
                            "distance_in": round(distance_cm / 2.54, 1),
                            "trigger_pin": args.trigger_pin,
                            "echo_pin": args.echo_pin,
                        }
                    ),
                    flush=True,
                )
            else:
                print(f"{distance_cm:.1f} cm ({distance_cm / 2.54:.1f} in)", flush=True)

            if args.once:
                break
            time.sleep(max(0.0, args.interval_sec))
    finally:
        sensor.close()


if __name__ == "__main__":
    main()
