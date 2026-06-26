"""HTTP service for hosted Agentech MuJoCo previews."""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .mujoco_sim import MuJoCoPreview


class SimulationRequest(BaseModel):
    code: str = Field(default="")
    max_render_frames: int = Field(default=32, ge=1, le=48)
    render_width: int = Field(default=480, ge=240, le=960)
    render_height: int = Field(default=320, ge=180, le=720)


app = FastAPI(title="Agentech MuJoCo Simulator", version="0.1.0")

allowed_origins = [
    origin.strip()
    for origin in os.environ.get(
        "AGENTECH_SIMULATOR_ALLOWED_ORIGINS",
        "http://localhost:3000,https://www.agent-tech.ai,https://agent-tech.ai",
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "agentech-mujoco-simulator"}


@app.post("/simulate")
def simulate(request: SimulationRequest) -> dict[str, Any]:
    try:
        preview = MuJoCoPreview.aegis()
        result = preview.run_code(request.code, timestep_s=0.02)
        sampled_frames = result.frames[:: max(1, len(result.frames) // 40)]
        if sampled_frames and sampled_frames[-1] != result.frames[-1]:
            sampled_frames.append(result.frames[-1])
        return {
            "model_path": result.model_path,
            "steps": result.steps,
            "duration_s": result.duration_s,
            "command_count": result.command_count,
            "final_pose": result.final_pose,
            "frames": sampled_frames,
            "rendered_frames": preview.render_data_urls(
                result.frames,
                max_frames=request.max_render_frames,
                width=request.render_width,
                height=request.render_height,
            ),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - return readable simulator failures to the website.
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc
