import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import agentech as agt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--key", default=None)
    parser.add_argument("--mode", choices=["dry_run", "simulation", "hardware"], default=None)
    parser.add_argument("--target", default=None)
    parser.add_argument("--allow-hardware", action="store_true")
    args = parser.parse_args()

    d = agt.Dog(
        key=args.key,
        mode=args.mode,
        target=args.target,
        allow_hardware=args.allow_hardware,
    )
    try:
        print(d.agt.stand())
        print(d.agt.set_forward_speed(0.3))
        print(d.agt.move_forward(1, unit="s"))
        print(d.agt.turn_left(90))
        print(d.agt.stop())
        print(d.agt.get_status())
    finally:
        print(d.close())


if __name__ == "__main__":
    main()
