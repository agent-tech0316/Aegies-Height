"""Print words heard from a USB microphone with offline speech recognition.

This uses Vosk locally, so it does not need an OpenAI API key or internet once
the speech model is downloaded.

Setup on the Pi:

  sudo apt-get install -y libportaudio2 unzip wget
  python3 -m venv ~/voice-test
  source ~/voice-test/bin/activate
  pip install sounddevice vosk

Download a small English model:

  mkdir -p ~/vosk-models
  cd ~/vosk-models
  wget https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
  unzip vosk-model-small-en-us-0.15.zip

Download a small Chinese model:

  cd ~/vosk-models
  wget https://alphacephei.com/vosk/models/vosk-model-small-cn-0.22.zip
  unzip vosk-model-small-cn-0.22.zip

List microphones:

  python examples/audio/transcribe_usb_mic_offline.py --list-devices

Run:

  python examples/audio/transcribe_usb_mic_offline.py \
    --input-device "USB" \
    --language en

Chinese:

  python examples/audio/transcribe_usb_mic_offline.py \
    --input-device "USB" \
    --language zh

Press Ctrl+C to stop.
"""
from __future__ import annotations

import argparse
import json
import queue
import sys
from pathlib import Path
from typing import Any


DEFAULT_MODEL_DIRS = {
    "en": "~/vosk-models/vosk-model-small-en-us-0.15",
    "zh": "~/vosk-models/vosk-model-small-cn-0.22",
}


def require_modules():
    try:
        import sounddevice as sd
        from vosk import KaldiRecognizer, Model
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "This script needs sounddevice and vosk. On Raspberry Pi, install with:\n"
            "  sudo apt-get install -y libportaudio2\n"
            "  python3 -m venv ~/voice-test\n"
            "  source ~/voice-test/bin/activate\n"
            "  pip install sounddevice vosk"
        ) from exc
    return sd, Model, KaldiRecognizer


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


def resolve_input_device(sd: Any, requested: int | str | None) -> int | None:
    if requested is None:
        default_device = sd.default.device[0]
        return None if default_device == -1 else int(default_device)

    if isinstance(requested, int):
        return requested

    devices = sd.query_devices()
    requested_lower = requested.lower()
    matches = [
        index
        for index, device in enumerate(devices)
        if requested_lower in device["name"].lower() and int(device["max_input_channels"]) > 0
    ]
    if not matches:
        raise RuntimeError(f"No input audio device matched: {requested!r}")
    if len(matches) > 1:
        names = ", ".join(f"{index}:{devices[index]['name']}" for index in matches)
        print(f"Multiple input matches found; using {matches[0]} from {names}", file=sys.stderr)
    return int(matches[0])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-devices", action="store_true", help="Print audio devices and exit.")
    parser.add_argument("--input-device", help="Input device index or name substring, for example USB.")
    parser.add_argument("--language", choices=sorted(DEFAULT_MODEL_DIRS), default="en")
    parser.add_argument("--model-dir", default=None, help="Override the model folder for a custom Vosk model.")
    parser.add_argument("--samplerate", type=int, default=0, help="0 means use the microphone default rate.")
    parser.add_argument("--blocksize", type=int, default=8000)
    parser.add_argument("--show-partials", action="store_true", help="Also print live partial guesses.")
    return parser


def result_text(raw_json: str, key: str) -> str:
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError:
        return ""
    return str(data.get(key, "")).strip()


def main() -> None:
    sd, Model, KaldiRecognizer = require_modules()
    args = build_parser().parse_args()

    if args.list_devices:
        list_devices(sd)
        return

    input_device = resolve_input_device(sd, parse_device_arg(args.input_device))
    if input_device is None:
        raise RuntimeError("No default input device found. Run with --list-devices and pass --input-device.")

    model_dir_arg = args.model_dir or DEFAULT_MODEL_DIRS[args.language]
    model_dir = Path(model_dir_arg).expanduser()
    if not model_dir.exists():
        raise RuntimeError(f"Vosk model folder not found: {model_dir}")

    input_info = sd.query_devices(input_device)
    samplerate = args.samplerate
    if samplerate <= 0:
        samplerate = int(round(float(input_info["default_samplerate"])))
    print(f"input: {input_device} - {input_info['name']}")
    print(f"samplerate: {samplerate}")
    print(f"model: {model_dir}")
    print("Listening. Speak into the mic. Press Ctrl+C to stop.")

    audio_queue: queue.Queue[bytes] = queue.Queue()

    def callback(indata, frames, time_info, status) -> None:
        del frames, time_info
        if status:
            print(status, file=sys.stderr)
        audio_queue.put(bytes(indata))

    model = Model(str(model_dir))
    recognizer = KaldiRecognizer(model, samplerate)

    try:
        with sd.RawInputStream(
            samplerate=samplerate,
            blocksize=args.blocksize,
            device=input_device,
            dtype="int16",
            channels=1,
            callback=callback,
        ):
            last_partial = ""
            while True:
                audio = audio_queue.get()
                if recognizer.AcceptWaveform(audio):
                    text = result_text(recognizer.Result(), "text")
                    if text:
                        print(f"heard: {text}", flush=True)
                    last_partial = ""
                elif args.show_partials:
                    partial = result_text(recognizer.PartialResult(), "partial")
                    if partial and partial != last_partial:
                        print(f"partial: {partial}", flush=True)
                        last_partial = partial
    except KeyboardInterrupt:
        final_text = result_text(recognizer.FinalResult(), "text")
        if final_text:
            print(f"\nheard: {final_text}")
        print("\nStopped.")


if __name__ == "__main__":
    main()
