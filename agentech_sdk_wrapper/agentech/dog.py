from __future__ import annotations

import os
from typing import Any

from .actions import AsyncDogActions, DogActions
from .adapters import DryRunAdapter, HardwareAdapter, SimulationAdapter
from .config import MODE_DRY_RUN, MODE_HARDWARE, MODE_SIMULATION, build_runtime_config
from .models import ActionResult
from .runtime import AsyncRunner


class AsyncDog:
    def __init__(
        self,
        key: str | None = None,
        *,
        mode: str | None = None,
        target: str | None = None,
        allow_hardware: bool | None = None,
        safe_max_forward_speed_mps: float | None = None,
        default_forward_speed_mps: float | None = None,
        yaw_rate_deg_s: float | None = None,
        dry_run_realtime: bool | None = None,
        simulation_realtime: bool | None = None,
    ) -> None:
        self.key = key
        self.config = build_runtime_config(
            key=key,
            mode=mode,
            allow_hardware=allow_hardware,
            safe_max_forward_speed_mps=safe_max_forward_speed_mps,
            default_forward_speed_mps=default_forward_speed_mps,
            yaw_rate_deg_s=yaw_rate_deg_s,
            dry_run_realtime=dry_run_realtime,
            simulation_realtime=simulation_realtime,
        )
        self.mode = self.config.mode
        self.target = self._resolve_target(target)
        self.forward_speed_mps = self.config.default_forward_speed_mps
        self.emergency_stopped = False
        self._adapter: Any | None = None
        self.agt = AsyncDogActions(self)

    def _resolve_target(self, target: str | None) -> str:
        if target:
            return target
        env_target = os.getenv("AGENTECH_TARGET")
        if env_target:
            return env_target
        if self.config.mode == MODE_HARDWARE and self.key:
            return self.key
        return self.config.default_target

    async def _get_adapter(self) -> Any:
        if self._adapter is not None:
            return self._adapter
        if self.config.mode == MODE_DRY_RUN:
            self._adapter = DryRunAdapter(config=self.config)
        elif self.config.mode == MODE_SIMULATION:
            self._adapter = SimulationAdapter(config=self.config)
        elif self.config.mode == MODE_HARDWARE:
            self._adapter = HardwareAdapter(config=self.config, target=self.target, key=self.key)
        else:
            raise RuntimeError(f"unknown Agentech mode: {self.config.mode}")
        await self._adapter.connect()
        return self._adapter

    async def close(self) -> ActionResult:
        return await self.agt.close()

    async def __aenter__(self) -> "AsyncDog":
        await self._get_adapter()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.close()


class Dog:
    def __init__(
        self,
        key: str | None = None,
        *,
        mode: str | None = None,
        target: str | None = None,
        allow_hardware: bool | None = None,
        safe_max_forward_speed_mps: float | None = None,
        default_forward_speed_mps: float | None = None,
        yaw_rate_deg_s: float | None = None,
        dry_run_realtime: bool | None = None,
        simulation_realtime: bool | None = None,
    ) -> None:
        self._runner = AsyncRunner()
        self._closed = False
        self._async_dog = AsyncDog(
            key=key,
            mode=mode,
            target=target,
            allow_hardware=allow_hardware,
            safe_max_forward_speed_mps=safe_max_forward_speed_mps,
            default_forward_speed_mps=default_forward_speed_mps,
            yaw_rate_deg_s=yaw_rate_deg_s,
            dry_run_realtime=dry_run_realtime,
            simulation_realtime=simulation_realtime,
        )
        self.key = self._async_dog.key
        self.mode = self._async_dog.mode
        self.target = self._async_dog.target
        self.agt = DogActions(self)

    def _run(self, coro: Any) -> Any:
        return self._runner.run(coro)

    def close(self) -> ActionResult:
        if self._closed:
            return ActionResult(status="ok", action="close", result={"already_closed": True})
        try:
            return self._run(self._async_dog.close())
        finally:
            self._closed = True
            self._runner.close()

    def __enter__(self) -> "Dog":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def __del__(self) -> None:
        if not getattr(self, "_closed", True):
            try:
                self.close()
            except Exception:
                pass

    def stand(self) -> ActionResult:
        return self.agt.stand()

    def sit(self) -> ActionResult:
        return self.agt.sit()

    def set_forward_speed(self, speed_mps: float) -> ActionResult:
        return self.agt.set_forward_speed(speed_mps)

    def move_forward(self, value: float, unit: str = "s") -> ActionResult:
        return self.agt.move_forward(value, unit=unit)

    def move_backward(self, value: float, unit: str = "s") -> ActionResult:
        return self.agt.move_backward(value, unit=unit)

    def turn_left(self, angle_deg: float) -> ActionResult:
        return self.agt.turn_left(angle_deg)

    def turn_right(self, angle_deg: float) -> ActionResult:
        return self.agt.turn_right(angle_deg)

    def rotate(self, angle_deg: float) -> ActionResult:
        return self.agt.rotate(angle_deg)

    def stop(self) -> ActionResult:
        return self.agt.stop()

    def emergency_stop(self, reason: str = "user") -> ActionResult:
        return self.agt.emergency_stop(reason=reason)

    def get_status(self) -> ActionResult:
        return self.agt.get_status()

    def capture_image(self) -> ActionResult:
        return self.agt.capture_image()

    def say(self, text: str) -> ActionResult:
        return self.agt.say(text)
