"""Check HC-SR04 depth sensor accuracy against measured distances.

Run on the Raspberry Pi with the sensor connected:

    python3 examples/vision/check_depth_sensor_accuracy.py

Default wiring:

    HC-SR04 trigger -> Raspberry Pi GPIO 17
    HC-SR04 echo    -> Raspberry Pi GPIO 27

Use a flat target such as a wall, box, or book. Measure from the front face of
the ultrasonic sensor to the target, then press Enter at each prompt.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path


DEFAULT_TRIGGER_PIN = 17
DEFAULT_ECHO_PIN = 27
DEFAULT_TEST_DISTANCES_CM = [20.0, 40.0, 60.0, 100.0, 150.0, 200.0]


@dataclass(frozen=True)
class AccuracyPoint:
    expected_cm: float
    median_cm: float
    mean_cm: float
    stdev_cm: float
    min_cm: float
    max_cm: float
    samples: int

    @property
    def error_cm(self) -> float:
        return self.median_cm - self.expected_cm

    @property
    def error_pct(self) -> float:
        return (self.error_cm / self.expected_cm) * 100.0


def require_distance_sensor():
    try:
        from gpiozero import DistanceSensor
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "This script needs gpiozero on the Raspberry Pi. "
            "Install with: python3 -m pip install gpiozero"
        ) from exc
    return DistanceSensor


def parse_distances(value: str) -> list[float]:
    distances = [float(part.strip()) for part in value.split(",") if part.strip()]
    if not distances:
        raise argparse.ArgumentTypeError("Provide at least one distance in centimeters.")
    for distance in distances:
        if distance <= 0:
            raise argparse.ArgumentTypeError("Distances must be positive centimeters.")
    return distances


def read_samples_cm(
    sensor,
    *,
    sample_count: int,
    sample_delay_sec: float,
    max_distance_cm: float,
) -> list[float]:
    samples: list[float] = []
    while len(samples) < sample_count:
        distance_cm = float(sensor.distance) * 100.0
        if math.isfinite(distance_cm) and 0.0 < distance_cm <= max_distance_cm:
            samples.append(distance_cm)
        time.sleep(max(0.0, sample_delay_sec))
    return samples


def summarize(expected_cm: float, samples: list[float]) -> AccuracyPoint:
    if not samples:
        raise RuntimeError("No valid samples were collected.")
    return AccuracyPoint(
        expected_cm=expected_cm,
        median_cm=float(statistics.median(samples)),
        mean_cm=float(statistics.mean(samples)),
        stdev_cm=float(statistics.stdev(samples)) if len(samples) > 1 else 0.0,
        min_cm=float(min(samples)),
        max_cm=float(max(samples)),
        samples=len(samples),
    )


def fit_linear_correction(points: list[AccuracyPoint]) -> dict[str, float] | None:
    if len(points) < 2:
        return None

    raw_values = [point.median_cm for point in points]
    expected_values = [point.expected_cm for point in points]
    raw_mean = statistics.mean(raw_values)
    expected_mean = statistics.mean(expected_values)
    denominator = sum((raw - raw_mean) ** 2 for raw in raw_values)
    if denominator == 0:
        return None

    scale = sum(
        (raw - raw_mean) * (expected - expected_mean)
        for raw, expected in zip(raw_values, expected_values)
    ) / denominator
    offset = expected_mean - scale * raw_mean
    corrected_errors = [
        (scale * point.median_cm + offset) - point.expected_cm
        for point in points
    ]
    mae_cm = statistics.mean(abs(error) for error in corrected_errors)
    max_abs_error_cm = max(abs(error) for error in corrected_errors)
    return {
        "scale": float(scale),
        "offset_cm": float(offset),
        "mean_abs_error_cm_after_correction": float(mae_cm),
        "max_abs_error_cm_after_correction": float(max_abs_error_cm),
    }


def print_point(point: AccuracyPoint) -> None:
    print(
        "expected={expected:.1f} cm  measured={measured:.1f} cm  "
        "error={error:+.1f} cm ({error_pct:+.1f}%)  stdev={stdev:.2f} cm  "
        "range={min_cm:.1f}-{max_cm:.1f} cm".format(
            expected=point.expected_cm,
            measured=point.median_cm,
            error=point.error_cm,
            error_pct=point.error_pct,
            stdev=point.stdev_cm,
            min_cm=point.min_cm,
            max_cm=point.max_cm,
        )
    )


def save_csv(path: Path, points: list[AccuracyPoint]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "expected_cm",
                "median_cm",
                "mean_cm",
                "stdev_cm",
                "min_cm",
                "max_cm",
                "samples",
                "error_cm",
                "error_pct",
            ],
        )
        writer.writeheader()
        for point in points:
            row = asdict(point)
            row["error_cm"] = point.error_cm
            row["error_pct"] = point.error_pct
            writer.writerow(row)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trigger-pin", type=int, default=DEFAULT_TRIGGER_PIN)
    parser.add_argument("--echo-pin", type=int, default=DEFAULT_ECHO_PIN)
    parser.add_argument("--distances-cm", type=parse_distances, default=DEFAULT_TEST_DISTANCES_CM)
    parser.add_argument("--samples", type=int, default=40)
    parser.add_argument("--sample-delay-sec", type=float, default=0.04)
    parser.add_argument("--settle-sec", type=float, default=0.4)
    parser.add_argument("--max-distance-cm", type=float, default=400.0)
    parser.add_argument("--csv-output", default="depth_sensor_accuracy.csv")
    parser.add_argument("--json-output", default="depth_sensor_accuracy.json")
    parser.add_argument("--no-save", action="store_true")
    parser.add_argument(
        "--no-prompt",
        action="store_true",
        help="Measure immediately without waiting for Enter at each distance.",
    )
    parser.add_argument(
        "--countdown-sec",
        type=float,
        default=0.0,
        help="Optional countdown before each no-prompt measurement.",
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

    points: list[AccuracyPoint] = []
    print("HC-SR04 depth sensor accuracy check")
    print(f"trigger_pin={args.trigger_pin} echo_pin={args.echo_pin}")
    print("Measure from the front face of the sensor to a flat target.")
    print("Keep the target square to the sensor for each reading.\n")

    try:
        for expected_cm in args.distances_cm:
            if args.no_prompt:
                if args.countdown_sec > 0:
                    print(
                        f"Measuring {expected_cm:.1f} cm in {args.countdown_sec:.1f}s...",
                        flush=True,
                    )
                    time.sleep(args.countdown_sec)
                else:
                    print(f"Measuring {expected_cm:.1f} cm now...", flush=True)
            else:
                input(f"Place target at {expected_cm:.1f} cm, then press Enter...")
            time.sleep(max(0.0, args.settle_sec))
            samples = read_samples_cm(
                sensor,
                sample_count=max(1, args.samples),
                sample_delay_sec=args.sample_delay_sec,
                max_distance_cm=args.max_distance_cm,
            )
            point = summarize(expected_cm, samples)
            points.append(point)
            print_point(point)
            print()
    finally:
        sensor.close()

    correction = fit_linear_correction(points)
    result = {
        "trigger_pin": args.trigger_pin,
        "echo_pin": args.echo_pin,
        "points": [
            {
                **asdict(point),
                "error_cm": point.error_cm,
                "error_pct": point.error_pct,
            }
            for point in points
        ],
        "correction": correction,
    }

    print("Summary")
    for point in points:
        print_point(point)

    if correction:
        print()
        print(
            "Correction formula: corrected_cm = "
            f"{correction['scale']:.6f} * raw_cm + {correction['offset_cm']:.3f}"
        )
        print(
            "After correction: mean_abs_error="
            f"{correction['mean_abs_error_cm_after_correction']:.2f} cm, "
            "max_abs_error="
            f"{correction['max_abs_error_cm_after_correction']:.2f} cm"
        )

    if not args.no_save:
        save_csv(Path(args.csv_output), points)
        Path(args.json_output).write_text(json.dumps(result, indent=2), encoding="utf-8")
        print()
        print(f"wrote_csv={args.csv_output}")
        print(f"wrote_json={args.json_output}")


if __name__ == "__main__":
    main()
