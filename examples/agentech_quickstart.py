"""Agentech wrapper quickstart.

Run in dry-run mode first:

    FF_SDK_DRY_RUN=1 python examples/agentech_quickstart.py
"""

from agentech import Agentech


def main() -> None:
    Agentech.stand(dry_run=True)
    Agentech.forward(speed=0.25, seconds=1.0, dry_run=True)
    Agentech.backward(speed=0.2, seconds=1.0, dry_run=True)
    Agentech.left(angle=45, dry_run=True)
    Agentech.right(angle=45, dry_run=True)
    Agentech.yaw(speed=0.25, seconds=1.0, dry_run=True)
    Agentech.look_up(angle=15, dry_run=True)
    Agentech.capture_image(output="height_photo.jpg", dry_run=True)
    Agentech.look_down(angle=15, dry_run=True)
    Agentech.capture_image(output="height_bottom.jpg", dry_run=True)
    Agentech.stop(dry_run=True)


if __name__ == "__main__":
    main()
