from __future__ import annotations

import dataclasses
import enum
import inspect
import math
from typing import Any

from .config import RuntimeConfig
from .exceptions import ConfigurationError


def to_plain(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return {"type": "bytes", "length": len(value)}
    if isinstance(value, enum.Enum):
        return value.value
    if dataclasses.is_dataclass(value):
        return to_plain(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {str(key): to_plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_plain(item) for item in value]
    if hasattr(value, "__dict__"):
        return {
            str(key): to_plain(item)
            for key, item in vars(value).items()
            if not key.startswith("_")
        }
    return repr(value)


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


class LocalAdapter:
    def __init__(self, *, mode: str, config: RuntimeConfig) -> None:
        self.mode = mode
        self.config = config
        self.connected = False
        self.emergency_stop_active = False
        self.current_velocity = {"linear_mps": 0.0, "angular_rad_s": 0.0, "lateral_mps": 0.0}
        self.events: list[dict[str, Any]] = []

    async def connect(self) -> None:
        self.connected = True

    def _record(self, action: str, **payload: Any) -> dict[str, Any]:
        event = {"mode": self.mode, "action": action, **payload}
        self.events.append(event)
        return event

    async def stand(self) -> dict[str, Any]:
        return self._record("stand")

    async def sit(self) -> dict[str, Any]:
        return self._record("sit")

    async def cmd_vel(
        self,
        *,
        linear: float = 0.0,
        angular: float = 0.0,
        lateral: float = 0.0,
    ) -> dict[str, Any]:
        self.current_velocity = {
            "linear_mps": linear,
            "angular_rad_s": angular,
            "lateral_mps": lateral,
        }
        return self._record("cmd_vel", **self.current_velocity)

    async def stop(self) -> dict[str, Any]:
        self.current_velocity = {"linear_mps": 0.0, "angular_rad_s": 0.0, "lateral_mps": 0.0}
        return self._record("stop")

    async def emergency_stop(self, *, reason: str) -> dict[str, Any]:
        self.emergency_stop_active = True
        self.current_velocity = {"linear_mps": 0.0, "angular_rad_s": 0.0, "lateral_mps": 0.0}
        return self._record("emergency_stop", reason=reason)

    async def status(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "connected": self.connected,
            "emergency_stop_active": self.emergency_stop_active,
            "current_velocity": dict(self.current_velocity),
            "events": len(self.events),
        }

    async def capture_image(self) -> dict[str, Any]:
        return {
            "supported": False,
            "image": None,
            "message": "capture_image is unavailable in local adapter modes",
        }

    async def say(self, *, text: str) -> dict[str, Any]:
        return {
            "supported": False,
            "text": text,
            "message": "say is unavailable in local adapter modes",
        }

    async def close(self) -> dict[str, Any]:
        self.connected = False
        return self._record("close")


class DryRunAdapter(LocalAdapter):
    def __init__(self, *, config: RuntimeConfig) -> None:
        super().__init__(mode="dry_run", config=config)


class SimulationAdapter(LocalAdapter):
    def __init__(self, *, config: RuntimeConfig) -> None:
        super().__init__(mode="simulation", config=config)
        self.pose = {"x_m": 0.0, "y_m": 0.0, "yaw_deg": 0.0}

    async def advance_linear(self, *, linear_mps: float, duration_s: float) -> dict[str, Any]:
        yaw_rad = math.radians(self.pose["yaw_deg"])
        distance_m = linear_mps * duration_s
        self.pose["x_m"] += math.cos(yaw_rad) * distance_m
        self.pose["y_m"] += math.sin(yaw_rad) * distance_m
        return self._record("advance_linear", distance_m=distance_m, duration_s=duration_s)

    async def advance_rotation(self, *, angle_deg: float) -> dict[str, Any]:
        self.pose["yaw_deg"] = (self.pose["yaw_deg"] + angle_deg) % 360.0
        return self._record("advance_rotation", angle_deg=angle_deg)

    async def status(self) -> dict[str, Any]:
        status = await super().status()
        status["pose"] = dict(self.pose)
        return status


class HardwareAdapter:
    mode = "hardware"

    def __init__(self, *, config: RuntimeConfig, target: str, key: str | None) -> None:
        self.config = config
        self.target = target
        self.key = key
        self.session: Any | None = None
        self._ff_sdk: Any | None = None

    async def connect(self) -> None:
        if self.session is not None:
            return
        try:
            import ff_sdk  # type: ignore
            from ff_sdk import Config  # type: ignore
        except ImportError as exc:
            raise ConfigurationError(
                "hardware mode requires ff_sdk to be installed in this Python environment"
            ) from exc

        self._ff_sdk = ff_sdk
        cfg = Config.from_env()
        self.session = await ff_sdk.connect(self.target, config=cfg)

    def _motion(self) -> Any:
        if self.session is None:
            raise RuntimeError("hardware adapter is not connected")
        motion = getattr(self.session, "motion", None)
        if motion is None:
            raise RuntimeError("ff_sdk session has no motion capability")
        return motion

    async def stand(self) -> dict[str, Any]:
        await self.connect()
        raw = await _maybe_await(self._motion().stand())
        return {"raw": to_plain(raw)}

    async def sit(self) -> dict[str, Any]:
        await self.connect()
        motion = self._motion()
        for name, args in (
            ("sit", ()),
            ("do_preset", ("sit",)),
            ("do_preset", ("lie_down",)),
            ("damping", ()),
        ):
            method = getattr(motion, name, None)
            if method is None:
                continue
            try:
                raw = await _maybe_await(method(*args))
            except Exception:
                if name == "damping":
                    raise
                continue
            return {"method": name, "raw": to_plain(raw)}
        raise RuntimeError("ff_sdk motion capability does not expose sit/do_preset/damping")

    async def cmd_vel(
        self,
        *,
        linear: float = 0.0,
        angular: float = 0.0,
        lateral: float = 0.0,
    ) -> dict[str, Any]:
        await self.connect()
        method = self._motion().cmd_vel
        try:
            raw = await _maybe_await(method(linear=linear, angular=angular, lateral=lateral))
        except TypeError:
            raw = await _maybe_await(method(linear=linear, angular=angular))
        return {
            "linear_mps": linear,
            "angular_rad_s": angular,
            "lateral_mps": lateral,
            "raw": to_plain(raw),
        }

    async def stop(self) -> dict[str, Any]:
        await self.connect()
        raw = await _maybe_await(self._motion().stop())
        return {"raw": to_plain(raw)}

    async def emergency_stop(self, *, reason: str) -> dict[str, Any]:
        await self.connect()
        try:
            raw = await _maybe_await(self.session.e_stop(reason=reason, source="agentech"))
        except TypeError:
            raw = await _maybe_await(self.session.e_stop(reason=reason))
        return {"reason": reason, "raw": to_plain(raw)}

    async def status(self) -> dict[str, Any]:
        await self.connect()
        state = getattr(self.session, "state", None)
        result: dict[str, Any] = {"mode": self.mode, "target": self.target}
        if state is None:
            result["state_supported"] = False
            return result
        for name in ("status", "battery", "pose"):
            method = getattr(state, name, None)
            if method is None:
                result[name] = {"supported": False}
                continue
            try:
                result[name] = to_plain(await _maybe_await(method()))
            except Exception as exc:
                result[name] = {"error": repr(exc)}
        return result

    async def capture_image(self) -> dict[str, Any]:
        await self.connect()
        for owner_name in ("camera", "vision", "image"):
            owner = getattr(self.session, owner_name, None)
            if owner is None:
                continue
            for method_name in ("capture_image", "capture", "snapshot", "read"):
                method = getattr(owner, method_name, None)
                if method is None:
                    continue
                raw = await _maybe_await(method())
                return {
                    "supported": True,
                    "owner": owner_name,
                    "method": method_name,
                    "image": to_plain(raw),
                }
        return {
            "supported": False,
            "image": None,
            "message": "ff_sdk session does not expose a known camera capture method",
        }

    async def say(self, *, text: str) -> dict[str, Any]:
        await self.connect()
        for owner_name in ("audio", "speech", "tts"):
            owner = getattr(self.session, owner_name, None)
            if owner is None:
                continue
            method = getattr(owner, "say", None) or getattr(owner, "speak", None)
            if method is None:
                continue
            raw = await _maybe_await(method(text))
            return {"supported": True, "owner": owner_name, "text": text, "raw": to_plain(raw)}
        return {
            "supported": False,
            "text": text,
            "message": "ff_sdk session does not expose a known speech method",
        }

    async def close(self) -> dict[str, Any]:
        if self.session is None:
            return {"connected": False}
        close = getattr(self.session, "close", None)
        raw = None
        if close is not None:
            raw = await _maybe_await(close())
        self.session = None
        return {"connected": False, "raw": to_plain(raw)}
