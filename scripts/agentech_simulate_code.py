"""Run pasted Agentech code through the local Aegis MuJoCo preview."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentech.mujoco_sim import MuJoCoPreview


def main() -> int:
    payload = json.load(sys.stdin)
    code = str(payload.get("code") or "")
    max_render_frames = int(payload.get("max_render_frames") or 12)
    render_width = int(payload.get("render_width") or 480)
    render_height = int(payload.get("render_height") or 320)
    preview = MuJoCoPreview.aegis()
    result = preview.run_code(code, timestep_s=0.02)
    sampled_frames = result.frames[:: max(1, len(result.frames) // 40)]
    if sampled_frames[-1] != result.frames[-1]:
        sampled_frames.append(result.frames[-1])
    print(
        json.dumps(
            {
                "model_path": result.model_path,
                "steps": result.steps,
                "duration_s": result.duration_s,
                "command_count": result.command_count,
                "final_pose": result.final_pose,
                "frames": sampled_frames,
                "rendered_frames": preview.render_data_urls(
                    result.frames,
                    max_frames=max_render_frames,
                    width=render_width,
                    height=render_height,
                ),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
