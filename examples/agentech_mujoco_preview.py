"""MuJoCo preview smoke test.

This requires an Aegis MJCF/XML model. Example:

    pip install -e ".[sim]"
    python examples/agentech_mujoco_preview.py --model models/aegis.xml
"""

from __future__ import annotations

import argparse

from agentech.mujoco_sim import MuJoCoCommand, MuJoCoPreview


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=None, help="Path to Aegis MuJoCo URDF/XML model.")
    args = parser.parse_args()

    preview = MuJoCoPreview(args.model) if args.model else MuJoCoPreview.aegis()
    result = preview.run(
        [
            MuJoCoCommand("stand", {}),
            MuJoCoCommand("forward", {"speed": 0.3, "seconds": 1.0}),
            MuJoCoCommand("yaw", {"speed": 0.35, "seconds": 1.0}),
        ]
    )
    print(result)


if __name__ == "__main__":
    main()
