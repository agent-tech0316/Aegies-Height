"""motion/attitude — D1 (quadruped) in-place attitude control（原地动作）.

D1-only. Tilts / turns / raises the body *in place* without walking:
  · pitch & yaw  → ride the right stick (continuous velocity)
  · peek (roll)  → left / right (X / B), discrete
  · stance height → high / low (Y / A), discrete

All four terms are VELOCITIES, clamped to ±0.5. The robot must be in the
in-place (STAY) motion mode first — otherwise the right stick is read as
locomotion, not attitude.

Backends:
  · aegis SDK (preferred) — true continuous 4-axis attitude velocity.
  · dog_task UDP fallback — pitch/yaw continuous via the right stick; peek &
    stance are discrete button pulses, so the fallback approximates roll/height
    by *direction*, not magnitude.

Usage:
    FF_SDK_DRY_RUN=1 python motion/attitude.py
    python motion/attitude.py --target D1-XG03
"""
from __future__ import annotations

import argparse
import asyncio
import logging

import ff_sdk
from ff_sdk import Config


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--target", default="D1-demo")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO)

    sess = await ff_sdk.connect(args.target, config=Config.from_env())
    try:
        motion = sess.motion

        # attitude_control is a D1-specific method (not on the generic
        # MotionCapability base) — guard so non-quadruped targets fail clearly.
        if not hasattr(motion, "attitude_control"):
            print(f"{args.target}: no attitude_control — D1 (quadruped) only")
            return

        # NOTE: enter in-place (STAY) mode first. aegis does this implicitly;
        # on the dog_task path send the STAY mode cmd before these calls.

        print(">> Pitch down 0.3 for 0.5 s（右摇杆后推 = 俯仰）")
        await motion.attitude_control(pitch_vel=-0.3)
        await asyncio.sleep(0.5)

        print(">> Yaw left 0.3 for 0.5 s（右摇杆左推 = 水平转身）")
        await motion.attitude_control(yaw_vel=0.3)
        await asyncio.sleep(0.5)

        print(">> Peek left + raise stance（探头 X + 高身形 Y）")
        await motion.attitude_control(roll_vel=0.4, height_vel=0.3)
        await asyncio.sleep(0.5)

        print(">> Neutral — hold still")
        await motion.attitude_control()  # all zero
    finally:
        await sess.close()


if __name__ == "__main__":
    asyncio.run(main())
