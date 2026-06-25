import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import agentech as agt


def main() -> None:
    d = agt.Dog(mode="simulation")
    try:
        print(d.agt.stand())
        print(d.agt.set_forward_speed(0.3))
        print(d.agt.move_forward(2, unit="m"))
        print(d.agt.turn_right(90))
        print(d.agt.move_backward(1, unit="m"))
        print(d.agt.get_status())
    finally:
        d.close()


if __name__ == "__main__":
    main()
