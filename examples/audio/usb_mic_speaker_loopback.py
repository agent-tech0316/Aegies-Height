"""Loop USB microphone audio to a speaker on a Raspberry Pi.

This is a hardware smoke test for the voice feature:

  USB microphone -> Raspberry Pi -> Sony speaker

List devices first:

  python examples/audio/usb_mic_speaker_loopback.py --list-devices

Then run with device names or indexes from that list:

  python examples/audio/usb_mic_speaker_loopback.py --input-device "USB" --output-device "Sony"

Press Ctrl+C to stop.
"""
from __future__ import annotations

import argparse
import sys
import time
from typing import Any


def require_audio_modules():
    try:
        import numpy as np
        import sounddevice as sd
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "This script needs sounddevice and numpy. On Raspberry Pi, install with:\n"
            "  sudo apt-get install -y libportaudio2\n"
            "  python3 -m pip install sounddevice numpy"
        ) from exc
    return np, sd


def parse_device_arg(value: str | None) -> int | str | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return value


def list_devices(sd: Any) -> None:
    print(sd.query_devices())
    print()
    print(f"default input/output device: {sd.default.device}")


def resolve_device(sd: Any, requested: int | str | None, *, kind: str) -> int | None:
    if requested is None:
        default_device = sd.default.device[0 if kind == "input" else 1]
        return None if default_device == -1 else int(default_device)

    if isinstance(requested, int):
        return requested

    devices = sd.query_devices()
    requested_lower = requested.lower()
    channel_key = "max_input_channels" if kind == "input" else "max_output_channels"
    matches = [
        index
        for index, device in enumerate(devices)
        if requested_lower in device["name"].lower() and int(device[channel_key]) > 0
    ]
    if not matches:
        raise RuntimeError(f"No {kind} audio device matched: {requested!r}")
    if len(matches) > 1:
        names = ", ".join(f"{index}:{devices[index]['name']}" for index in matches)
        print(f"Multiple {kind} matches found; using {matches[0]} from {names}", file=sys.stderr)
    return int(matches[0])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-devices", action="store_true", help="Print audio devices and exit.")
    parser.add_argument("--input-device", help="Input device index or name substring, for example USB.")
    parser.add_argument("--output-device", help="Output device index or name substring, for example Sony.")
    parser.add_argument("--samplerate", type=int, default=44100)
    parser.add_argument("--channels", type=int, default=1)
    parser.add_argument("--blocksize", type=int, default=1024)
    parser.add_argument("--gain", type=float, default=1.0, help="Playback gain. Keep near 1.0 to avoid feedback.")
    parser.add_argument("--duration-sec", type=float, default=0.0, help="0 means run until Ctrl+C.")
    return parser


def main() -> None:
    np, sd = require_audio_modules()
    args = build_parser().parse_args()

    if args.list_devices:
        list_devices(sd)
        return

    input_device = resolve_device(sd, parse_device_arg(args.input_device), kind="input")
    output_device = resolve_device(sd, parse_device_arg(args.output_device), kind="output")

    if input_device is None:
        raise RuntimeError("No default input device found. Run with --list-devices and pass --input-device.")
    if output_device is None:
        raise RuntimeError("No default output device found. Run with --list-devices and pass --output-device.")

    input_info = sd.query_devices(input_device)
    output_info = sd.query_devices(output_device)
    print(f"input : {input_device} - {input_info['name']}")
    print(f"output: {output_device} - {output_info['name']}")
    print("Looping microphone to speaker. Press Ctrl+C to stop.")

    def callback(indata, outdata, frames, time_info, status) -> None:
        del frames, time_info
        if status:
            print(status, file=sys.stderr)

        audio = indata
        if audio.shape[1] < args.channels:
            audio = np.repeat(audio, args.channels, axis=1)
        audio = audio[:, : args.channels] * float(args.gain)
        outdata[:] = np.clip(audio, -1.0, 1.0)

    try:
        with sd.Stream(
            device=(input_device, output_device),
            samplerate=args.samplerate,
            blocksize=args.blocksize,
            channels=args.channels,
            dtype="float32",
            callback=callback,
        ):
            started_at = time.monotonic()
            while args.duration_sec <= 0.0 or time.monotonic() - started_at < args.duration_sec:
                time.sleep(0.2)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
