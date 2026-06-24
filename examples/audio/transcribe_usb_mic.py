"""Print words heard from a USB microphone.

This records short chunks from a Raspberry Pi audio input and sends each chunk
to OpenAI speech-to-text. Use this when the offline Vosk model is too slow or
you need mixed English/Chinese transcription.

Setup on the Pi:

  sudo apt-get install -y libportaudio2
  python3 -m venv ~/voice-test
  source ~/voice-test/bin/activate
  pip install sounddevice numpy openai
  export OPENAI_API_KEY="your_api_key_here"

List microphone devices:

  python examples/audio/transcribe_usb_mic.py --list-devices

Run with a USB mic device index or name substring:

  python examples/audio/transcribe_usb_mic.py --input-device "USB"

Press Ctrl+C to stop.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
import time
import wave
from pathlib import Path
from typing import Any


def require_modules():
    try:
        import numpy as np
        import sounddevice as sd
        from openai import OpenAI
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "This script needs sounddevice, numpy, and openai. On Raspberry Pi, install with:\n"
            "  sudo apt-get install -y libportaudio2\n"
            "  python3 -m pip install sounddevice numpy openai"
        ) from exc
    return np, sd, OpenAI


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


def write_wav(path: Path, samples, *, samplerate: int) -> None:
    clipped = samples.clip(-1.0, 1.0)
    pcm16 = (clipped * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(samplerate)
        wav.writeframes(pcm16.tobytes())


def record_chunk(np: Any, sd: Any, *, device: int, samplerate: int, seconds: float):
    frames = int(round(samplerate * seconds))
    audio = sd.rec(
        frames,
        samplerate=samplerate,
        channels=1,
        dtype="float32",
        device=device,
    )
    sd.wait()
    return np.asarray(audio).reshape(-1)


def rms(np: Any, samples) -> float:
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(samples))))


def transcribe_file(
    client: Any,
    audio_path: Path,
    *,
    model: str,
    language: str | None,
    prompt: str,
) -> str:
    with audio_path.open("rb") as audio_file:
        kwargs: dict[str, object] = {
            "model": model,
            "file": audio_file,
            "response_format": "text",
        }
        if language:
            kwargs["language"] = language
        if prompt:
            kwargs["prompt"] = prompt
        transcript = client.audio.transcriptions.create(**kwargs)
    return str(transcript).strip()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-devices", action="store_true", help="Print audio devices and exit.")
    parser.add_argument("--input-device", help="Input device index or name substring, for example USB.")
    parser.add_argument("--samplerate", type=int, default=0, help="0 means use the microphone default rate.")
    parser.add_argument("--chunk-sec", type=float, default=2.0, help="Seconds recorded per transcription request.")
    parser.add_argument("--silence-rms", type=float, default=0.008, help="Skip chunks quieter than this RMS value.")
    parser.add_argument("--model", default="gpt-4o-mini-transcribe")
    parser.add_argument("--language", default=None, help="Optional language hint, for example en or zh.")
    parser.add_argument(
        "--prompt",
        default="Transcribe exactly. The speaker may mix English and Chinese. Preserve Chinese characters and English words.",
    )
    parser.add_argument("--keep-wav-dir", default=None, help="Optional folder to keep recorded WAV chunks.")
    return parser


def main() -> None:
    np, sd, OpenAI = require_modules()
    args = build_parser().parse_args()

    if args.list_devices:
        list_devices(sd)
        return

    input_device = resolve_input_device(sd, parse_device_arg(args.input_device))
    if input_device is None:
        raise RuntimeError("No default input device found. Run with --list-devices and pass --input-device.")

    input_info = sd.query_devices(input_device)
    samplerate = args.samplerate
    if samplerate <= 0:
        samplerate = int(round(float(input_info["default_samplerate"])))
    print(f"input: {input_device} - {input_info['name']}")
    print(f"samplerate: {samplerate}")
    print(f"model: {args.model}")
    print("Listening. Speak after each 'recording...' line. Press Ctrl+C to stop.")

    client = OpenAI()
    keep_dir = Path(args.keep_wav_dir) if args.keep_wav_dir else None
    if keep_dir:
        keep_dir.mkdir(parents=True, exist_ok=True)

    chunk_index = 1
    try:
        while True:
            print("recording...", flush=True)
            samples = record_chunk(
                np,
                sd,
                device=input_device,
                samplerate=samplerate,
                seconds=args.chunk_sec,
            )
            level = rms(np, samples)
            if level < args.silence_rms:
                print(f"(quiet: rms={level:.4f})")
                continue

            if keep_dir:
                wav_path = keep_dir / f"mic_chunk_{chunk_index:04d}.wav"
            else:
                temp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                temp.close()
                wav_path = Path(temp.name)

            try:
                write_wav(wav_path, samples, samplerate=samplerate)
                text = transcribe_file(
                    client,
                    wav_path,
                    model=args.model,
                    language=args.language,
                    prompt=args.prompt,
                )
                if text:
                    print(f"heard: {text}", flush=True)
                else:
                    print("(no words recognized)")
            finally:
                if keep_dir is None:
                    wav_path.unlink(missing_ok=True)

            chunk_index += 1
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
