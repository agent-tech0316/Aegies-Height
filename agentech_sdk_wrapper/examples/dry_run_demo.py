import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import agentech as agt


def main() -> None:
    d = agt.Dog(mode="dry_run")
    try:
        print(d.agt.stand())
        print(d.agt.set_forward_speed(0.3))
        print(d.agt.move_forward(1, unit="m"))
        print(d.agt.rotate(-45))
        print(d.agt.stop())
        print(d.agt.get_status())
    finally:
        d.close()


if __name__ == "__main__":
    main()
