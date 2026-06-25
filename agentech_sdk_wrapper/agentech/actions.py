from __future__ import annotations

import asyncio
import math
import uuid
from typing import Any, Callable

from .config import MODE_DRY_RUN, MODE_HARDWARE, MODE_SIMULATION
from .exceptions import SafetyError
from .models import ActionResult


def _trace_id() -> str:
    return uuid.uuid4().hex


class AsyncDogActions:
    def __init__(self, dog: Any) -> None:
        self._dog = dog

    def _result(
        self,
        *,
        status: str,
        action: str,
        result: dict[str, Any],
        trace_id: str,
    ) -> ActionResult:
        return ActionResult(status=status, action=action, result=result, trace_id=trace_id)

    async def _adapter(self) -> Any:
        return await self._dog._get_adapter()

    async def _sleep(self, duration_s: float) -> None:
        mode = self._dog.config.mode
        if mode == MODE_HARDWARE:
            await asyncio.sleep(duration_s)
        elif mode == MODE_SIMULATION and self._dog.config.simulation_realtime:
            await asyncio.sleep(duration_s)
        elif mode == MODE_DRY_RUN and self._dog.config.dry_run_realtime:
            await asyncio.sleep(duration_s)

    def _ensure_motion_allowed(self, action: str) -> None:
        if self._dog.emergency_stopped:
            raise SafetyError(
                f"{action} is blocked because emergency_stop is active; reset policy is not defined"
            )

    def _duration_from_value(self, value: float, unit: str) -> tuple[float, float]:
        if value <= 0:
            raise ValueError("move value must be > 0")
        if unit == "s":
            return value, self._dog.forward_speed_mps * value
        if unit == "m":
            return value / self._dog.forward_speed_mps, value
        raise ValueError("unit must be 's' or 'm'")

    async def stand(self) -> ActionResult:
        trace_id = _trace_id()
        self._ensure_motion_allowed("stand")
        raw = await (await self._adapter()).stand()
        return self._result(status="ok", action="stand", result={"mode": self._dog.mode, "raw": raw}, trace_id=trace_id)

    async def sit(self) -> ActionResult:
        trace_id = _trace_id()
        self._ensure_motion_allowed("sit")
        raw = await (await self._adapter()).sit()
        return self._result(status="ok", action="sit", result={"mode": self._dog.mode, "raw": raw}, trace_id=trace_id)

    async def set_forward_speed(self, speed_mps: float) -> ActionResult:
        trace_id = _trace_id()
        if speed_mps <= 0:
            raise ValueError("speed_mps must be > 0")
        if speed_mps > self._dog.config.safe_max_forward_speed_mps:
            raise ValueError(
                "speed_mps must be <= safe_max_speed "
                f"({self._dog.config.safe_max_forward_speed_mps:.3f} m/s)"
            )
        self._dog.forward_speed_mps = speed_mps
        return self._result(
            status="ok",
            action="set_forward_speed",
            result={
                "speed_mps": speed_mps,
                "safe_max_speed_mps": self._dog.config.safe_max_forward_speed_mps,
            },
            trace_id=trace_id,
        )

    async def move_forward(self, value: float, unit: str = "s") -> ActionResult:
        return await self._move(direction=1.0, action="move_forward", value=value, unit=unit)

    async def move_backward(self, value: float, unit: str = "s") -> ActionResult:
        return await self._move(direction=-1.0, action="move_backward", value=value, unit=unit)

    async def _move(self, *, direction: float, action: str, value: float, unit: str) -> ActionResult:
        trace_id = _trace_id()
        self._ensure_motion_allowed(action)
        duration_s, distance_m = self._duration_from_value(value, unit)
        signed_speed = direction * self._dog.forward_speed_mps
        adapter = await self._adapter()
        stop_raw = None
        await adapter.cmd_vel(linear=signed_speed, angular=0.0, lateral=0.0)
        try:
            if hasattr(adapter, "advance_linear"):
                await adapter.advance_linear(linear_mps=signed_speed, duration_s=duration_s)
            await self._sleep(duration_s)
        finally:
            stop_raw = await adapter.stop()
        return self._result(
            status="ok",
            action=action,
            result={
                "mode": self._dog.mode,
                "unit": unit,
                "value": value,
                "speed_mps": self._dog.forward_speed_mps,
                "duration_s": duration_s,
                "distance_m": distance_m,
                "stop": stop_raw,
            },
            trace_id=trace_id,
        )

    async def turn_left(self, angle_deg: float) -> ActionResult:
        if angle_deg <= 0:
            raise ValueError("angle_deg must be > 0")
        return await self.rotate(angle_deg)

    async def turn_right(self, angle_deg: float) -> ActionResult:
        if angle_deg <= 0:
            raise ValueError("angle_deg must be > 0")
        return await self.rotate(-angle_deg)

    async def rotate(self, angle_deg: float) -> ActionResult:
        trace_id = _trace_id()
        self._ensure_motion_allowed("rotate")
        if angle_deg == 0:
            raise ValueError("angle_deg must be non-zero")
        sign = 1.0 if angle_deg > 0 else -1.0
        yaw_rate_deg_s = self._dog.config.yaw_rate_deg_s
        angular_rad_s = sign * math.radians(yaw_rate_deg_s)
        duration_s = abs(angle_deg) / yaw_rate_deg_s
        adapter = await self._adapter()
        stop_raw = None
        await adapter.cmd_vel(linear=0.0, angular=angular_rad_s, lateral=0.0)
        try:
            if hasattr(adapter, "advance_rotation"):
                await adapter.advance_rotation(angle_deg=angle_deg)
            await self._sleep(duration_s)
        finally:
            stop_raw = await adapter.stop()
        return self._result(
            status="ok",
            action="rotate",
            result={
                "mode": self._dog.mode,
                "angle_deg": angle_deg,
                "yaw_rate_deg_s": yaw_rate_deg_s,
                "angular_rad_s": angular_rad_s,
                "duration_s": duration_s,
                "direction": "left" if angle_deg > 0 else "right",
                "stop": stop_raw,
            },
            trace_id=trace_id,
        )

    async def stop(self) -> ActionResult:
        trace_id = _trace_id()
        raw = await (await self._adapter()).stop()
        return self._result(status="ok", action="stop", result={"mode": self._dog.mode, "raw": raw}, trace_id=trace_id)

    async def emergency_stop(self, reason: str = "user") -> ActionResult:
        trace_id = _trace_id()
        self._dog.emergency_stopped = True
        raw = await (await self._adapter()).emergency_stop(reason=reason)
        return self._result(
            status="ok",
            action="emergency_stop",
            result={
                "mode": self._dog.mode,
                "reason": reason,
                "blocks_future_motion": True,
                "raw": raw,
            },
            trace_id=trace_id,
        )

    async def get_status(self) -> ActionResult:
        trace_id = _trace_id()
        raw = await (await self._adapter()).status()
        return self._result(
            status="ok",
            action="get_status",
            result={
                "mode": self._dog.mode,
                "forward_speed_mps": self._dog.forward_speed_mps,
                "safe_max_forward_speed_mps": self._dog.config.safe_max_forward_speed_mps,
                "emergency_stop_active": self._dog.emergency_stopped,
                "raw": raw,
            },
            trace_id=trace_id,
        )

    async def capture_image(self) -> ActionResult:
        trace_id = _trace_id()
        raw = await (await self._adapter()).capture_image()
        status = "ok" if raw.get("supported") else "unsupported"
        return self._result(status=status, action="capture_image", result={"mode": self._dog.mode, "raw": raw}, trace_id=trace_id)

    async def say(self, text: str) -> ActionResult:
        trace_id = _trace_id()
        raw = await (await self._adapter()).say(text=text)
        status = "ok" if raw.get("supported") else "unsupported"
        return self._result(status=status, action="say", result={"mode": self._dog.mode, "text": text, "raw": raw}, trace_id=trace_id)

    async def close(self) -> ActionResult:
        trace_id = _trace_id()
        if self._dog._adapter is None:
            raw = {"connected": False, "initialized": False}
        else:
            raw = await self._dog._adapter.close()
        return self._result(status="ok", action="close", result={"mode": self._dog.mode, "raw": raw}, trace_id=trace_id)


class DogActions:
    def __init__(self, dog: Any) -> None:
        self._dog = dog

    def _run(self, method_name: str, *args: Any, **kwargs: Any) -> ActionResult:
        method: Callable[..., Any] = getattr(self._dog._async_dog.agt, method_name)
        return self._dog._run(method(*args, **kwargs))

    def stand(self) -> ActionResult:
        return self._run("stand")

    def sit(self) -> ActionResult:
        return self._run("sit")

    def set_forward_speed(self, speed_mps: float) -> ActionResult:
        return self._run("set_forward_speed", speed_mps)

    def move_forward(self, value: float, unit: str = "s") -> ActionResult:
        return self._run("move_forward", value, unit=unit)

    def move_backward(self, value: float, unit: str = "s") -> ActionResult:
        return self._run("move_backward", value, unit=unit)

    def turn_left(self, angle_deg: float) -> ActionResult:
        return self._run("turn_left", angle_deg)

    def turn_right(self, angle_deg: float) -> ActionResult:
        return self._run("turn_right", angle_deg)

    def rotate(self, angle_deg: float) -> ActionResult:
        return self._run("rotate", angle_deg)

    def stop(self) -> ActionResult:
        return self._run("stop")

    def emergency_stop(self, reason: str = "user") -> ActionResult:
        return self._run("emergency_stop", reason=reason)

    def get_status(self) -> ActionResult:
        return self._run("get_status")

    def capture_image(self) -> ActionResult:
        return self._run("capture_image")

    def say(self, text: str) -> ActionResult:
        return self._run("say", text)
