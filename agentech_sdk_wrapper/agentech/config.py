from __future__ import annotations

import os
import platform
from dataclasses import dataclass, field

from .exceptions import ConfigurationError

MODE_DRY_RUN = "dry_run"
MODE_SIMULATION = "simulation"
MODE_HARDWARE = "hardware"
SUPPORTED_MODES = {MODE_DRY_RUN, MODE_SIMULATION, MODE_HARDWARE}

# Algorithm-team measurements supplied for the first wrapper pass.
THEORETICAL_MAX_FORWARD_SPEED_MPS: float | None = 2.37  # 90ft / 11.58s
SAFE_MAX_FORWARD_SPEED_RATIO = 0.95
CONSERVATIVE_SAFE_MAX_FORWARD_SPEED_MPS = 0.5


def compute_safe_max_forward_speed(
    theoretical_max_forward_speed_mps: float | None = THEORETICAL_MAX_FORWARD_SPEED_MPS,
) -> float:
    if theoretical_max_forward_speed_mps is None:
        return CONSERVATIVE_SAFE_MAX_FORWARD_SPEED_MPS
    return theoretical_max_forward_speed_mps * SAFE_MAX_FORWARD_SPEED_RATIO


SAFE_MAX_FORWARD_SPEED_MPS = compute_safe_max_forward_speed()

ALGORITHM_SLOW_FORWARD_SPEED_MPS = 1.10  # 90ft / 25s
DEFAULT_SLOW_FORWARD_SPEED_MPS = 0.3

MAX_BACKWARD_SPEED_MPS = 2.36  # 90ft / 11.6s
MAX_LATERAL_SPEED_MPS = 0.78  # 90ft / 35.37s

FAST_YAW_RATE_DEG_S = 120  # 3s / circle
SLOW_YAW_RATE_DEG_S = 60  # 6s / circle
DEFAULT_YAW_RATE_DEG_S = 60

GAIT_STEP_LENGTH_M = 0.669  # 90ft / 41 steps

MAX_SIDE_TILT_DEG = 28  # 90 - 62
MAX_FORWARD_TILT_DEG = 19  # 90 - 71
MAX_BACKWARD_TILT_DEG = 21  # 90 - 69

VERTICAL_MOVE_UP_CM = 6
VERTICAL_MOVE_DOWN_CM = 11

STRAIGHT_TEST_DISTANCE_M = 18.288  # 60ft
STRAIGHT_END_ERROR_M = 1.27  # 50in
STRAIGHT_MAX_ERROR_M = 1.524  # 5ft
STRAIGHT_END_ERROR_RATIO = 0.069
STRAIGHT_MAX_ERROR_RATIO = 0.083

DEFAULT_TARGET = "D1-DEMO"


def _env_truthy(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _normalize_mode(mode: str | None) -> str | None:
    if mode is None:
        return None
    normalized = mode.strip().lower()
    if normalized not in SUPPORTED_MODES:
        allowed = ", ".join(sorted(SUPPORTED_MODES))
        raise ConfigurationError(f"Unsupported Agentech mode {mode!r}; expected one of: {allowed}")
    return normalized


def select_mode(
    *,
    key: str | None,
    requested_mode: str | None = None,
    allow_hardware: bool | None = None,
    platform_name: str | None = None,
) -> str:
    env_mode = _normalize_mode(os.getenv("AGENTECH_MODE"))
    mode = _normalize_mode(requested_mode) or env_mode
    hardware_allowed = (
        _env_truthy("AGENTECH_ALLOW_HARDWARE", default=False)
        if allow_hardware is None
        else allow_hardware
    )
    system_name = platform_name or platform.system()

    if mode == MODE_HARDWARE:
        if not key and not os.getenv("AGENTECH_TARGET"):
            raise ConfigurationError("hardware mode requires key=... or AGENTECH_TARGET")
        if not hardware_allowed:
            raise ConfigurationError(
                "hardware mode requires allow_hardware=True or AGENTECH_ALLOW_HARDWARE=1"
            )
        if system_name == "Windows":
            raise ConfigurationError("hardware mode is not enabled on Windows by default")
        return MODE_HARDWARE

    if mode is not None:
        return mode

    if not key:
        return MODE_DRY_RUN
    if hardware_allowed and system_name != "Windows":
        return MODE_HARDWARE
    return MODE_SIMULATION


@dataclass(frozen=True)
class RuntimeConfig:
    mode: str
    allow_hardware: bool
    safe_max_forward_speed_mps: float = SAFE_MAX_FORWARD_SPEED_MPS
    default_forward_speed_mps: float = DEFAULT_SLOW_FORWARD_SPEED_MPS
    yaw_rate_deg_s: float = DEFAULT_YAW_RATE_DEG_S
    default_target: str = DEFAULT_TARGET
    dry_run_realtime: bool = False
    simulation_realtime: bool = False
    hardware_supported_platforms: tuple[str, ...] = field(default_factory=lambda: ("Linux",))


def build_runtime_config(
    *,
    key: str | None,
    mode: str | None = None,
    allow_hardware: bool | None = None,
    safe_max_forward_speed_mps: float | None = None,
    default_forward_speed_mps: float | None = None,
    yaw_rate_deg_s: float | None = None,
    dry_run_realtime: bool | None = None,
    simulation_realtime: bool | None = None,
) -> RuntimeConfig:
    resolved_allow_hardware = (
        _env_truthy("AGENTECH_ALLOW_HARDWARE", default=False)
        if allow_hardware is None
        else allow_hardware
    )
    resolved_mode = select_mode(
        key=key,
        requested_mode=mode,
        allow_hardware=resolved_allow_hardware,
    )
    safe_max = (
        safe_max_forward_speed_mps
        if safe_max_forward_speed_mps is not None
        else SAFE_MAX_FORWARD_SPEED_MPS
    )
    default_speed = (
        default_forward_speed_mps
        if default_forward_speed_mps is not None
        else DEFAULT_SLOW_FORWARD_SPEED_MPS
    )
    yaw_rate = yaw_rate_deg_s if yaw_rate_deg_s is not None else DEFAULT_YAW_RATE_DEG_S

    if safe_max <= 0:
        raise ConfigurationError("safe_max_forward_speed_mps must be > 0")
    if default_speed <= 0:
        raise ConfigurationError("default_forward_speed_mps must be > 0")
    if default_speed > safe_max:
        raise ConfigurationError("default_forward_speed_mps must be <= safe_max_forward_speed_mps")
    if yaw_rate <= 0:
        raise ConfigurationError("yaw_rate_deg_s must be > 0")

    return RuntimeConfig(
        mode=resolved_mode,
        allow_hardware=resolved_allow_hardware,
        safe_max_forward_speed_mps=safe_max,
        default_forward_speed_mps=default_speed,
        yaw_rate_deg_s=yaw_rate,
        dry_run_realtime=(
            _env_truthy("AGENTECH_DRY_RUN_REALTIME", default=False)
            if dry_run_realtime is None
            else dry_run_realtime
        ),
        simulation_realtime=(
            _env_truthy("AGENTECH_SIMULATION_REALTIME", default=False)
            if simulation_realtime is None
            else simulation_realtime
        ),
    )
