"""Read HC-SR04 distance only when a foreground object appears.

This is for the project setup where the sensor points at a background wall.
The script first learns the wall/background distance, then only prints readings
when something is clearly closer than that baseline.

Run on the Raspberry Pi:

    python3 examples/vision/read_depth_foreground_object.py
"""
from __future__ import annotations

import argparse
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


def read_sample_cm(sensor, max_distance_cm: float) -> float | None:
    distance_cm = float(sensor.distance) * 100.0
    if math.isfinite(distance_cm) and 0.0 < distance_cm <= max_distance_cm:
        return distance_cm
    return None


def read_median_cm(
    sensor,
    *,
    samples: int,
    sample_delay_sec: float,
    max_distance_cm: float,
) -> float | None:
    values: list[float] = []
    for _ in range(max(1, samples)):
        value = read_sample_cm(sensor, max_distance_cm)
        if value is not None:
            values.append(value)
        time.sleep(max(0.0, sample_delay_sec))
    if not values:
        return None
    return float(statistics.median(values))


def learn_background_cm(
    sensor,
    *,
    seconds: float,
    sample_delay_sec: float,
    max_distance_cm: float,
) -> float:
    values: list[float] = []
    deadline = time.monotonic() + max(0.1, seconds)
    while time.monotonic() < deadline:
        value = read_sample_cm(sensor, max_distance_cm)
        if value is not None:
            values.append(value)
        time.sleep(max(0.0, sample_delay_sec))
    if not values:
        raise RuntimeError("Could not learn background distance; no valid sensor samples.")
    return float(statistics.median(values))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trigger-pin", type=int, default=DEFAULT_TRIGGER_PIN)
    parser.add_argument("--echo-pin", type=int, default=DEFAULT_ECHO_PIN)
    parser.add_argument("--baseline-sec", type=float, default=3.0)
    parser.add_argument("--threshold-cm", type=float, default=12.0)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--sample-delay-sec", type=float, default=0.04)
    parser.add_argument("--interval-sec", type=float, default=0.15)
    parser.add_argument("--max-distance-cm", type=float, default=400.0)
    parser.add_argument(
        "--show-ignored",
        action="store_true",
        help="Also print wall/background readings that are being suppressed.",
    )
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
        print("Keep only the wall/background in front of the sensor.", flush=True)
        print(f"Learning background for {args.baseline_sec:.1f}s...", flush=True)
        background_cm = learn_background_cm(
            sensor,
            seconds=args.baseline_sec,
            sample_delay_sec=args.sample_delay_sec,
            max_distance_cm=args.max_distance_cm,
        )
        trigger_cm = max(0.0, background_cm - args.threshold_cm)
        print(
            f"background={background_cm:.1f} cm; "
            f"printing only objects closer than {trigger_cm:.1f} cm",
            flush=True,
        )

        while True:
            distance_cm = read_median_cm(
                sensor,
                samples=args.samples,
                sample_delay_sec=args.sample_delay_sec,
                max_distance_cm=args.max_distance_cm,
            )
            if distance_cm is None:
                time.sleep(max(0.0, args.interval_sec))
                continue

            if distance_cm <= trigger_cm:
                closer_by_cm = background_cm - distance_cm
                print(
                    f"OBJECT {distance_cm:.1f} cm ({distance_cm / 2.54:.1f} in), "
                    f"closer_by={closer_by_cm:.1f} cm",
                    flush=True,
                )
            elif args.show_ignored:
                print(f"ignored_wall {distance_cm:.1f} cm", flush=True)

            time.sleep(max(0.0, args.interval_sec))
    finally:
        sensor.close()


if __name__ == "__main__":
    main()
