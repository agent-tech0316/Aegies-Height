"""MuJoCo simulation hooks for Agentech command previews.

This module is intentionally separate from the beginner control API. The web
preview can call this backend once an Aegis MJCF/XML model is available.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import ast
import base64
import io
import math
import re
from typing import Any


DEFAULT_AEGIS_MODEL_PATH = Path(__file__).resolve().parent / "assets" / "aegis" / "urdf" / "Aegis_mujoco_floating.urdf"
LEGS = ("FL", "FR", "RR", "RL")
LEG_PHASE = {"FL": 0.0, "RR": 0.0, "FR": math.pi, "RL": math.pi}
GAIT_RATE_HZ = 1.55
STAND_HIP = 0.58
STAND_KNEE = -1.08


@dataclass(frozen=True)
class MuJoCoCommand:
    action: str
    params: dict[str, Any]


@dataclass(frozen=True)
class MuJoCoPreviewResult:
    model_path: str
    steps: int
    duration_s: float
    command_count: int
    frames: list[dict[str, float]]
    final_pose: dict[str, float]


def parse_agentech_code(code: str) -> list[MuJoCoCommand]:
    """Extract simple Agentech calls from beginner Python code."""

    def literal(node: ast.AST) -> Any:
        try:
            return ast.literal_eval(node)
        except (TypeError, ValueError):
            return None

    def call_params(call: ast.Call) -> dict[str, Any]:
        params: dict[str, Any] = {}
        for keyword in call.keywords:
            if keyword.arg is None:
                continue
            value = literal(keyword.value)
            if isinstance(value, (int, float, str, bool)):
                params[keyword.arg] = value
        return params

    commands: list[MuJoCoCommand] = []
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            owner = node.func.value
            if not isinstance(owner, ast.Name) or owner.id not in {"Agentech", "dog"}:
                continue

            action = node.func.attr
            if action == "run_sequence" and node.args:
                actions = literal(node.args[0])
                if isinstance(actions, list):
                    for item in actions:
                        if not isinstance(item, dict):
                            continue
                        nested_action = item.get("action")
                        nested_params = item.get("params", {})
                        if isinstance(nested_action, str) and isinstance(nested_params, dict):
                            commands.append(MuJoCoCommand(action=nested_action, params=nested_params))
                    continue
            commands.append(MuJoCoCommand(action=action, params=call_params(node)))
        if commands:
            return commands
    except SyntaxError:
        pass

    call_pattern = re.compile(r"(?:Agentech|dog)\.(\w+)\((.*)\)")
    number_pattern = re.compile(r"(\w+)\s*=\s*(-?\d+(?:\.\d+)?)")
    string_pattern = re.compile(r"(\w+)\s*=\s*['\"]([^'\"]+)['\"]")

    for raw_line in code.splitlines():
        line = raw_line.strip()
        match = call_pattern.search(line)
        if not match:
            continue
        action, raw_args = match.groups()
        params: dict[str, Any] = {}
        params.update({key: float(value) for key, value in number_pattern.findall(raw_args)})
        params.update({key: value for key, value in string_pattern.findall(raw_args)})
        commands.append(MuJoCoCommand(action=action, params=params))

    return commands


def _quat_multiply(left: list[float], right: list[float]) -> list[float]:
    lw, lx, ly, lz = left
    rw, rx, ry, rz = right
    return [
        lw * rw - lx * rx - ly * ry - lz * rz,
        lw * rx + lx * rw + ly * rz - lz * ry,
        lw * ry - lx * rz + ly * rw + lz * rx,
        lw * rz + lx * ry - ly * rx + lz * rw,
    ]


def _quat_from_yaw(yaw_rad: float) -> list[float]:
    yaw_half = yaw_rad / 2.0
    return [math.cos(yaw_half), 0.0, 0.0, math.sin(yaw_half)]


def _smoothstep(edge0: float, edge1: float, value: float) -> float:
    if value <= edge0:
        return 0.0
    if value >= edge1:
        return 1.0
    x = (value - edge0) / (edge1 - edge0)
    return x * x * (3.0 - 2.0 * x)


def _style_aegis_model(model: Any, mujoco: Any) -> None:
    """Mirror the public FF demo styling so the imported URDF is readable."""

    body_shell = [0.92, 0.95, 1.00, 1.0]
    hip_shell = [1.00, 0.52, 0.12, 1.0]
    leg_shell = [0.18, 0.22, 0.28, 1.0]
    foot_shell = [0.05, 0.06, 0.07, 1.0]

    for geom_id in range(model.ngeom):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, geom_id)
        if name in {"floor", "runway", "start_pad", "goal_pad"}:
            continue
        if model.geom_group[geom_id] == 0:
            model.geom_rgba[geom_id] = [0.0, 0.0, 0.0, 0.0]
            continue

        body_name = (
            mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, int(model.geom_bodyid[geom_id]))
            or ""
        )
        if body_name == "BASE_LINK":
            model.geom_rgba[geom_id] = body_shell
        elif "ABAD" in body_name or "HIP" in body_name:
            model.geom_rgba[geom_id] = hip_shell
        elif "FOOT" in body_name:
            model.geom_rgba[geom_id] = foot_shell
        else:
            model.geom_rgba[geom_id] = leg_shell


def _build_ff_preview_model(mujoco: Any, model_path: Path, width: int = 640, height: int = 480) -> Any:
    """Build the Aegis model with the same world elements as FF's demo video."""

    try:
        spec = mujoco.MjSpec.from_file(str(model_path))
    except AttributeError:
        return mujoco.MjModel.from_xml_path(str(model_path))

    spec.visual.global_.offwidth = max(640, width)
    spec.visual.global_.offheight = max(480, height)
    spec.option.timestep = 0.002
    spec.option.gravity = [0.0, 0.0, -9.81]

    world = spec.worldbody
    world.add_geom(
        name="floor",
        type=mujoco.mjtGeom.mjGEOM_PLANE,
        size=[0, 0, 0.05],
        rgba=[0.06, 0.07, 0.08, 1],
    )
    world.add_geom(
        name="runway",
        type=mujoco.mjtGeom.mjGEOM_BOX,
        pos=[0.05, 0, 0.002],
        size=[0.62, 0.24, 0.002],
        rgba=[0.10, 0.13, 0.16, 1],
    )
    world.add_geom(
        name="start_pad",
        type=mujoco.mjtGeom.mjGEOM_BOX,
        pos=[-0.35, 0, 0.006],
        size=[0.08, 0.20, 0.003],
        rgba=[0.15, 0.38, 1.00, 0.75],
    )
    world.add_geom(
        name="goal_pad",
        type=mujoco.mjtGeom.mjGEOM_BOX,
        pos=[0.40, 0, 0.007],
        size=[0.08, 0.20, 0.004],
        rgba=[0.25, 1.00, 0.45, 0.80],
    )
    world.add_light(pos=[0, -1.1, 2.4], dir=[0, 0.35, -1], diffuse=[1.0, 1.0, 1.0])
    world.add_light(pos=[-1.0, 0.8, 1.5], dir=[0.4, -0.3, -1], diffuse=[0.5, 0.55, 0.65])
    world.add_camera(
        name="demo_camera",
        pos=[1.35, -1.05, 0.42],
        xyaxes=[0.9, 0.44, 0, -0.12, 0.24, 0.96],
    )
    return spec.compile()


def _update_ff_demo_camera(model: Any, mujoco: Any, data: Any, camera: Any, time_s: float) -> None:
    """Use the camera path from FF's public Aegis MuJoCo demo."""

    base_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "BASE_LINK")
    if base_id >= 0:
        lookat = data.xpos[base_id].copy()
    else:
        lookat = [0.0, 0.0, 0.25]
    lookat[2] = 0.17
    camera.type = mujoco.mjtCamera.mjCAMERA_FREE
    camera.lookat[:] = lookat
    if time_s < 2.1:
        camera.distance = 1.15
        camera.azimuth = 98.0 + 3.0 * math.sin(1.1 * time_s)
        camera.elevation = -18.0
    elif time_s < 4.2:
        blend = _smoothstep(2.1, 4.2, time_s)
        camera.distance = 1.25 - 0.10 * blend
        camera.azimuth = 122.0 + 22.0 * blend
        camera.elevation = -19.0 + 2.0 * blend
    else:
        camera.distance = 1.10
        camera.azimuth = 178.0 + 4.0 * math.sin(1.0 * time_s)
        camera.elevation = -17.0


def _joint_qpos_addresses(model: Any, mujoco: Any) -> dict[str, int]:
    addresses: dict[str, int] = {}
    for leg in LEGS:
        for joint in ("ABAD", "HIP", "KNEE"):
            name = f"{leg}_{joint}_JOINT"
            joint_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, name)
            if joint_id >= 0:
                addresses[name] = int(model.jnt_qposadr[joint_id])
    return addresses


def _clip_joint(model: Any, mujoco: Any, joint_name: str, value: float) -> float:
    joint_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, joint_name)
    if joint_id >= 0 and model.jnt_limited[joint_id]:
        low, high = model.jnt_range[joint_id]
        return max(float(low), min(float(high), value))
    return value


def _apply_ff_demo_gait(
    model: Any,
    mujoco: Any,
    data: Any,
    joint_addresses: dict[str, int],
    gait_phase: float,
    settle: float,
    direction: float,
) -> None:
    """Use the same public Aegis gait math shipped in FF's MuJoCo demo."""

    for leg in LEGS:
        phase = gait_phase * direction + LEG_PHASE[leg]
        swing = math.sin(phase)
        lift = max(0.0, swing)
        targets = {
            "ABAD": settle * 0.10 * math.sin(phase + 0.4),
            "HIP": STAND_HIP + settle * 0.32 * swing,
            "KNEE": STAND_KNEE + settle * 0.34 * lift,
        }
        for joint, value in targets.items():
            joint_name = f"{leg}_{joint}_JOINT"
            address = joint_addresses.get(joint_name)
            if address is not None:
                data.qpos[address] = _clip_joint(model, mujoco, joint_name, value)


class MuJoCoPreview:
    """Load the Aegis MuJoCo model and execute beginner Agentech commands."""

    def __init__(self, model_path: str | Path = DEFAULT_AEGIS_MODEL_PATH) -> None:
        self.model_path = Path(model_path)

    @classmethod
    def aegis(cls) -> "MuJoCoPreview":
        return cls(DEFAULT_AEGIS_MODEL_PATH)

    def run(
        self,
        commands: list[MuJoCoCommand],
        *,
        duration_s: float | None = None,
        timestep_s: float = 0.01,
    ) -> MuJoCoPreviewResult:
        if not self.model_path.exists():
            raise FileNotFoundError(f"MuJoCo model not found: {self.model_path}")

        try:
            import mujoco
        except ImportError as exc:
            raise RuntimeError("Install MuJoCo support with: pip install 'agentech[sim]'") from exc

        model = _build_ff_preview_model(mujoco, self.model_path)
        _style_aegis_model(model, mujoco)
        data = mujoco.MjData(model)
        root_qpos = int(model.jnt_qposadr[0]) if model.njnt else 0
        if model.nq < root_qpos + 7:
            raise RuntimeError("Aegis MuJoCo model must have a floating root joint.")

        x = 0.0
        y = 0.0
        z = 0.33
        yaw = 0.0
        pitch = 0.0
        gait_phase = 0.0
        time_s = 0.0
        frames: list[dict[str, float]] = []
        steps = 0

        def set_root_pose(*, gait_settle: float = 0.0, gait_direction: float = 1.0) -> None:
            data.qpos[root_qpos : root_qpos + 3] = [x, y, z]
            data.qpos[root_qpos + 3 : root_qpos + 7] = _quat_from_yaw(yaw)
            mujoco.mj_forward(model, data)
            frames.append(
                {
                    "x": x,
                    "y": y,
                    "z": z,
                    "yaw": math.degrees(yaw),
                    "pitch": math.degrees(pitch),
                    "gait_phase": gait_phase,
                    "gait_settle": gait_settle,
                    "gait_direction": gait_direction,
                    "time_s": time_s,
                }
            )

        set_root_pose()

        for command in commands:
            action = command.action
            params = command.params
            if action in {"stand", "sit", "stop", "emergency_stop", "say", "get_status", "capture_image"}:
                set_root_pose()
                continue

            if action in {"forward", "backward"}:
                speed = abs(float(params.get("speed", 0.3)))
                seconds = float(params.get("seconds", 1.0))
                direction = 1.0 if action == "forward" else -1.0
                count = max(1, int(seconds / timestep_s))
                for _ in range(count):
                    time_s += timestep_s
                    gait_phase += 2.0 * math.pi * GAIT_RATE_HZ * timestep_s
                    z = 0.33 + 0.02 * math.sin(gait_phase)
                    x += math.cos(yaw) * direction * speed * timestep_s
                    y += math.sin(yaw) * direction * speed * timestep_s
                    set_root_pose(gait_settle=1.0, gait_direction=direction)
                    steps += 1
                z = 0.33
                continue

            if action in {"left", "turn_left", "right", "turn_right", "rotate", "yaw"}:
                if action == "yaw":
                    yaw_rate = float(params.get("speed", 0.35))
                    seconds = float(params.get("seconds", 1.0))
                    count = max(1, int(seconds / timestep_s))
                    yaw_delta = yaw_rate * timestep_s
                else:
                    angle = float(params.get("angle", 45.0 if action != "rotate" else 90.0))
                    if action in {"right", "turn_right"}:
                        angle = -abs(angle)
                    elif action in {"left", "turn_left"}:
                        angle = abs(angle)
                    yaw_rate = abs(float(params.get("speed", 0.35)))
                    seconds = max(timestep_s, abs(math.radians(angle)) / yaw_rate)
                    count = max(1, int(seconds / timestep_s))
                    yaw_delta = math.radians(angle) / count
                for _ in range(count):
                    time_s += timestep_s
                    gait_phase += 2.0 * math.pi * GAIT_RATE_HZ * timestep_s
                    z = 0.33 + 0.015 * math.sin(gait_phase)
                    yaw += yaw_delta
                    turn_direction = 1.0 if yaw_delta >= 0 else -1.0
                    set_root_pose(gait_settle=1.0, gait_direction=turn_direction)
                    steps += 1
                z = 0.33

            if action in {"pitch", "camera_pitch", "look_up", "look_down"}:
                if action == "pitch":
                    pitch_rate = float(params.get("speed", 0.12))
                    seconds = float(params.get("seconds", 0.5))
                    count = max(1, int(seconds / timestep_s))
                    pitch_delta = pitch_rate * timestep_s
                else:
                    angle = float(params.get("angle", 10.0))
                    if action == "look_down":
                        angle = -abs(angle)
                    elif action == "look_up":
                        angle = abs(angle)
                    pitch_rate = abs(float(params.get("speed", 0.12)))
                    seconds = max(timestep_s, abs(math.radians(angle)) / pitch_rate)
                    count = max(1, int(seconds / timestep_s))
                    pitch_delta = math.radians(angle) / count
                for _ in range(count):
                    time_s += timestep_s
                    pitch = max(math.radians(-45), min(math.radians(45), pitch + pitch_delta))
                    set_root_pose()
                    steps += 1

        return MuJoCoPreviewResult(
            model_path=str(self.model_path),
            steps=steps,
            duration_s=duration_s if duration_s is not None else steps * timestep_s,
            command_count=len(commands),
            frames=frames,
            final_pose=frames[-1],
        )

    def run_code(self, code: str, *, timestep_s: float = 0.01) -> MuJoCoPreviewResult:
        return self.run(parse_agentech_code(code), timestep_s=timestep_s)

    def render_data_urls(
        self,
        frames: list[dict[str, float]],
        *,
        max_frames: int = 18,
        width: int = 520,
        height: int = 360,
    ) -> list[str]:
        """Render selected preview frames from the real Aegis MuJoCo model."""

        if not frames:
            return []

        try:
            import mujoco
            from PIL import Image
        except ImportError as exc:
            raise RuntimeError("Install MuJoCo preview support with: pip install -e '.[sim]'") from exc

        model = _build_ff_preview_model(mujoco, self.model_path, width=width, height=height)
        _style_aegis_model(model, mujoco)
        data = mujoco.MjData(model)
        root_qpos = int(model.jnt_qposadr[0]) if model.njnt else 0
        joint_addresses = _joint_qpos_addresses(model, mujoco)
        renderer = mujoco.Renderer(model, height=height, width=width)
        camera = mujoco.MjvCamera()
        camera.type = mujoco.mjtCamera.mjCAMERA_FREE

        stride = max(1, len(frames) // max_frames)
        selected = frames[::stride][:max_frames]
        if selected[-1] is not frames[-1]:
            selected.append(frames[-1])

        images: list[str] = []
        try:
            for frame in selected:
                yaw_rad = math.radians(float(frame.get("yaw", 0.0)))
                x = float(frame.get("x", 0.0))
                y = float(frame.get("y", 0.0))
                z = float(frame.get("z", 0.33))
                gait_phase = float(frame.get("gait_phase", 0.0))
                gait_settle = float(frame.get("gait_settle", 0.0))
                gait_direction = float(frame.get("gait_direction", 1.0))
                time_s = float(frame.get("time_s", 0.0))
                data.qpos[root_qpos : root_qpos + 3] = [x, y, z]
                data.qpos[root_qpos + 3 : root_qpos + 7] = _quat_from_yaw(yaw_rad)
                _apply_ff_demo_gait(model, mujoco, data, joint_addresses, gait_phase, gait_settle, gait_direction)
                mujoco.mj_forward(model, data)
                _update_ff_demo_camera(model, mujoco, data, camera, time_s)
                renderer.update_scene(data, camera=camera)
                image = Image.fromarray(renderer.render())
                buffer = io.BytesIO()
                image.save(buffer, format="PNG", optimize=True)
                encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
                images.append(f"data:image/png;base64,{encoded}")
        finally:
            renderer.close()

        return images
