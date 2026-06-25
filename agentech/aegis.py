"""Simple Agentech API over the FF Aegis SDK.

This module intentionally keeps the public API small:

    Agentech.forward()
    Agentech.backward()
    Agentech.turn_left()
    Agentech.turn_right()
    Agentech.rotate()
    Agentech.yaw()
    Agentech.look_up()
    Agentech.look_down()
    Agentech.camera_pitch()
    Agentech.stand()
    Agentech.sit()
    Agentech.stop()
    Agentech.emergency_stop()
    Agentech.get_status()
    Agentech.capture_image()
    Agentech.run_sequence([...])

The FF SDK is async-first. This wrapper hides that for beginner scripts while
still offering a persistent context manager for multi-step routines.
"""
from __future__ import annotations

import asyncio
import inspect
import math
import os
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any


DEFAULT_TARGET = "D1-DEMO"
DEFAULT_SPEED_MPS = 0.3
DEFAULT_YAW_RATE = 0.35
DEFAULT_PITCH_RATE = 0.12
DEFAULT_SECONDS = 1.0
MAX_SPEED_MPS = 2.37
MAX_YAW_RATE = 2.09
MAX_PITCH_RATE = 0.5
MAX_SECONDS = 10.0
MAX_LOOK_UP_DEGREES = 20.0
MAX_LOOK_DOWN_DEGREES = 25.0
MAX_TEXT_LENGTH = 180


def _clamp(value: float, minimum: float, maximum: float, name: str) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc
    if numeric < minimum or numeric > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return numeric


def _run_sync(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    raise RuntimeError(
        "Agentech one-line methods cannot run inside an active asyncio loop. "
        "Use the FF SDK directly or call the async methods on Robot."
    )


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "value"):
        return value.value
    if hasattr(value, "__dict__"):
        return {key: _jsonable(item) for key, item in vars(value).items() if not key.startswith("_")}
    return repr(value)


class Robot:
    """Persistent robot connection for simple multi-step scripts."""

    def __init__(
        self,
        target: str = DEFAULT_TARGET,
        *,
        host: str | None = None,
        variant: str | None = None,
        dry_run: bool | None = None,
        auto_stop: bool = True,
    ) -> None:
        self.target = target
        self.host = host
        self.variant = variant
        self.dry_run = dry_run
        self.auto_stop = auto_stop
        self._session: Any | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._is_stopped = True

    def __enter__(self) -> "Robot":
        self.connect()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def connect(self) -> "Robot":
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
        return self._loop.run_until_complete(self._connect())

    async def _connect(self) -> "Robot":
        if self._session is not None:
            return self

        if self.dry_run is not None:
            os.environ["FF_SDK_DRY_RUN"] = "1" if self.dry_run else "0"
        if self.host:
            os.environ["FF_SDK_D1_HOST"] = self.host
        if self.variant:
            os.environ["FF_SDK_D1_VARIANT"] = self.variant

        import ff_sdk
        from ff_sdk import Config

        cfg = Config.from_env()
        if self.host:
            cfg.extra["d1_host"] = self.host
        if self.variant:
            cfg.extra["d1_variant"] = self.variant

        self._session = await ff_sdk.connect(self.target, config=cfg)
        return self

    def close(self) -> None:
        if self._loop is None:
            return None
        try:
            return self._loop.run_until_complete(self._close())
        finally:
            self._loop.close()
            self._loop = None

    def _sync(self, coro: Any) -> Any:
        if self._loop is not None:
            return self._loop.run_until_complete(coro)
        return _run_sync(coro)

    async def _close(self) -> None:
        if self._session is None:
            return
        if self.auto_stop and not self._is_stopped:
            await self._stop()
        await self._session.close()
        self._session = None

    @property
    def session(self) -> Any:
        if self._session is None:
            raise RuntimeError("Robot is not connected. Use 'with Agentech.robot() as dog:' first.")
        return self._session

    def stand(self) -> Any:
        return self._sync(self._stand())

    async def _stand(self) -> Any:
        return await self.session.motion.stand()

    def sit(self) -> Any:
        return self._sync(self._sit())

    async def _sit(self) -> Any:
        motion = self.session.motion
        if hasattr(motion, "sit"):
            return await motion.sit()
        return await motion.do_preset("lie_down")

    def stop(self) -> Any:
        return self._sync(self._stop())

    async def _stop(self) -> Any:
        result = await self.session.motion.stop()
        self._is_stopped = True
        return result

    def damping(self) -> Any:
        return self._sync(self._damping())

    async def _damping(self) -> Any:
        result = await self.session.motion.damping()
        self._is_stopped = True
        return result

    def forward(self, speed: float = DEFAULT_SPEED_MPS, seconds: float = DEFAULT_SECONDS, *, stop: bool = True) -> Any:
        return self._sync(self._forward(speed=speed, seconds=seconds, stop=stop))

    async def _forward(self, speed: float = DEFAULT_SPEED_MPS, seconds: float = DEFAULT_SECONDS, *, stop: bool = True) -> Any:
        speed = _clamp(speed, 0.0, MAX_SPEED_MPS, "speed")
        seconds = _clamp(seconds, 0.0, MAX_SECONDS, "seconds")
        self._is_stopped = speed == 0.0
        await self.session.motion.cmd_vel(linear=speed, angular=0.0)
        await asyncio.sleep(seconds)
        if stop:
            return await self._stop()
        return None

    def backward(self, speed: float = DEFAULT_SPEED_MPS, seconds: float = DEFAULT_SECONDS, *, stop: bool = True) -> Any:
        return self._sync(self._backward(speed=speed, seconds=seconds, stop=stop))

    async def _backward(self, speed: float = DEFAULT_SPEED_MPS, seconds: float = DEFAULT_SECONDS, *, stop: bool = True) -> Any:
        speed = _clamp(speed, 0.0, MAX_SPEED_MPS, "speed")
        seconds = _clamp(seconds, 0.0, MAX_SECONDS, "seconds")
        self._is_stopped = speed == 0.0
        await self.session.motion.cmd_vel(linear=-speed, angular=0.0)
        await asyncio.sleep(seconds)
        if stop:
            return await self._stop()
        return None

    def yaw(self, speed: float = DEFAULT_YAW_RATE, seconds: float = DEFAULT_SECONDS, *, stop: bool = True) -> Any:
        return self._sync(self._yaw(speed=speed, seconds=seconds, stop=stop))

    async def _yaw(self, speed: float = DEFAULT_YAW_RATE, seconds: float = DEFAULT_SECONDS, *, stop: bool = True) -> Any:
        speed = _clamp(speed, -MAX_YAW_RATE, MAX_YAW_RATE, "speed")
        seconds = _clamp(seconds, 0.0, MAX_SECONDS, "seconds")
        self._is_stopped = speed == 0.0
        await self.session.motion.cmd_vel(linear=0.0, angular=speed)
        await asyncio.sleep(seconds)
        if stop:
            return await self._stop()
        return None

    def rotate(self, angle: float = 90.0, speed: float = DEFAULT_YAW_RATE, *, stop: bool = True) -> Any:
        return self._sync(self._rotate(angle=angle, speed=speed, stop=stop))

    async def _rotate(self, angle: float = 90.0, speed: float = DEFAULT_YAW_RATE, *, stop: bool = True) -> Any:
        angle = _clamp(angle, -360.0, 360.0, "angle")
        speed = _clamp(abs(speed), 0.05, MAX_YAW_RATE, "speed")
        seconds = min(abs(math.radians(angle)) / speed, MAX_SECONDS)
        direction = 1.0 if angle >= 0 else -1.0
        return await self._yaw(speed=direction * speed, seconds=seconds, stop=stop)

    def turn_left(self, angle: float = 45.0, speed: float = DEFAULT_YAW_RATE, *, stop: bool = True) -> Any:
        return self._sync(self._turn_left(angle=angle, speed=speed, stop=stop))

    async def _turn_left(self, angle: float = 45.0, speed: float = DEFAULT_YAW_RATE, *, stop: bool = True) -> Any:
        return await self._rotate(angle=abs(angle), speed=speed, stop=stop)

    def left(self, angle: float = 45.0, speed: float = DEFAULT_YAW_RATE, *, stop: bool = True) -> Any:
        return self.turn_left(angle=angle, speed=speed, stop=stop)

    async def _left(self, angle: float = 45.0, speed: float = DEFAULT_YAW_RATE, *, stop: bool = True) -> Any:
        return await self._turn_left(angle=angle, speed=speed, stop=stop)

    def turn_right(self, angle: float = 45.0, speed: float = DEFAULT_YAW_RATE, *, stop: bool = True) -> Any:
        return self._sync(self._turn_right(angle=angle, speed=speed, stop=stop))

    async def _turn_right(self, angle: float = 45.0, speed: float = DEFAULT_YAW_RATE, *, stop: bool = True) -> Any:
        return await self._rotate(angle=-abs(angle), speed=speed, stop=stop)

    def right(self, angle: float = 45.0, speed: float = DEFAULT_YAW_RATE, *, stop: bool = True) -> Any:
        return self.turn_right(angle=angle, speed=speed, stop=stop)

    async def _right(self, angle: float = 45.0, speed: float = DEFAULT_YAW_RATE, *, stop: bool = True) -> Any:
        return await self._turn_right(angle=angle, speed=speed, stop=stop)

    def pitch(self, speed: float = DEFAULT_PITCH_RATE, seconds: float = 0.5, *, stop: bool = True, hz: float = 20.0) -> Any:
        return self._sync(self._pitch(speed=speed, seconds=seconds, stop=stop, hz=hz))

    async def _pitch(self, speed: float = DEFAULT_PITCH_RATE, seconds: float = 0.5, *, stop: bool = True, hz: float = 20.0) -> Any:
        speed = _clamp(speed, -MAX_PITCH_RATE, MAX_PITCH_RATE, "speed")
        seconds = _clamp(seconds, 0.0, MAX_SECONDS, "seconds")
        motion = self.session.motion
        if not hasattr(motion, "attitude_control"):
            raise RuntimeError("FF SDK motion.attitude_control(...) is required for camera/body pitch.")
        last: Any = None
        hz = _clamp(hz, 1.0, 50.0, "hz")
        interval = 1.0 / hz
        count = max(1, int(round(seconds * hz)))
        for _ in range(count):
            self._is_stopped = speed == 0.0
            last = await motion.attitude_control(pitch_vel=speed)
            await asyncio.sleep(interval)
        if stop:
            await motion.attitude_control()
            self._is_stopped = True
        return last

    def camera_pitch(self, angle: float = 10.0, speed: float = DEFAULT_PITCH_RATE, *, stop: bool = True) -> Any:
        return self._sync(self._camera_pitch(angle=angle, speed=speed, stop=stop))

    async def _camera_pitch(self, angle: float = 10.0, speed: float = DEFAULT_PITCH_RATE, *, stop: bool = True) -> Any:
        angle = _clamp(angle, -MAX_LOOK_DOWN_DEGREES, MAX_LOOK_UP_DEGREES, "angle")
        speed = _clamp(abs(speed), 0.03, MAX_PITCH_RATE, "speed")
        seconds = min(abs(math.radians(angle)) / speed, MAX_SECONDS)
        direction = 1.0 if angle >= 0 else -1.0
        return await self._pitch(speed=direction * speed, seconds=seconds, stop=stop)

    def look_up(self, angle: float = 10.0, speed: float = DEFAULT_PITCH_RATE, *, stop: bool = True) -> Any:
        return self._sync(self._look_up(angle=angle, speed=speed, stop=stop))

    async def _look_up(self, angle: float = 10.0, speed: float = DEFAULT_PITCH_RATE, *, stop: bool = True) -> Any:
        return await self._camera_pitch(angle=abs(angle), speed=speed, stop=stop)

    def look_down(self, angle: float = 10.0, speed: float = DEFAULT_PITCH_RATE, *, stop: bool = True) -> Any:
        return self._sync(self._look_down(angle=angle, speed=speed, stop=stop))

    async def _look_down(self, angle: float = 10.0, speed: float = DEFAULT_PITCH_RATE, *, stop: bool = True) -> Any:
        return await self._camera_pitch(angle=-abs(angle), speed=speed, stop=stop)

    def emergency_stop(self, reason: str = "Agentech emergency stop") -> Any:
        return self._sync(self._emergency_stop(reason=reason))

    async def _emergency_stop(self, reason: str = "Agentech emergency stop") -> Any:
        result = await self.session.e_stop(reason=reason, source="agentech")
        self._is_stopped = True
        return result

    def get_status(self) -> dict[str, Any]:
        return self._sync(self._get_status())

    async def _get_status(self) -> dict[str, Any]:
        status = await self.session.state.status()
        payload: dict[str, Any] = {
            "target": self.target,
            "status": _jsonable(status),
            "emergency_stop": bool(getattr(self.session.estop, "is_active", False)),
        }
        for name, getter in (
            ("battery", self.session.state.battery),
            ("pose", self.session.state.pose),
        ):
            try:
                payload[name] = _jsonable(await getter())
            except Exception as exc:  # noqa: BLE001 - status should degrade gracefully.
                payload[name] = {"error": f"{type(exc).__name__}: {exc}"}
        return payload

    def capture_image(self, output: str | Path = "agentech_capture.jpg", source: str = "default") -> str | None:
        return self._sync(self._capture_image(output=output, source=source))

    async def _capture_image(self, output: str | Path = "agentech_capture.jpg", source: str = "default") -> str | None:
        frame = await self.session.vision.frame(source)
        data = getattr(frame, "data", b"")
        if not data:
            return None
        path = Path(output)
        path.write_bytes(data)
        return str(path)

    def say(self, text: str) -> dict[str, str]:
        return self._sync(self._say(text))

    async def _say(self, text: str) -> dict[str, str]:
        text = str(text).strip()
        if not text:
            raise ValueError("text cannot be empty")
        if len(text) > MAX_TEXT_LENGTH:
            raise ValueError(f"text must be {MAX_TEXT_LENGTH} characters or fewer")
        print(text)
        return {"spoken_text": text}

    def run_sequence(self, actions: Iterable[dict[str, Any]]) -> list[Any]:
        return self._sync(self._run_sequence(actions))

    async def _run_sequence(self, actions: Iterable[dict[str, Any]]) -> list[Any]:
        results: list[Any] = []
        for item in actions:
            action = str(item.get("action", "")).strip()
            params = dict(item.get("params", {}))
            method = getattr(self, f"_{action}", None)
            if method is None or action.startswith("_"):
                raise ValueError(f"Unsupported Agentech action: {action}")
            result = method(**params)
            if inspect.isawaitable(result):
                result = await result
            results.append(result)
        return results


class Agentech:
    """One-line entry point for students and demos."""

    @staticmethod
    def robot(
        target: str = DEFAULT_TARGET,
        *,
        host: str | None = None,
        variant: str | None = None,
        dry_run: bool | None = None,
        auto_stop: bool = True,
    ) -> Robot:
        return Robot(target=target, host=host, variant=variant, dry_run=dry_run, auto_stop=auto_stop)

    @staticmethod
    def _once(func: Callable[[Robot], Any], **connect_kwargs: Any) -> Any:
        async def runner() -> Any:
            dog = Robot(**connect_kwargs)
            await dog._connect()
            try:
                result = func(dog)
                if inspect.isawaitable(result):
                    return await result
                return result
            finally:
                await dog._close()

        return _run_sync(runner())

    @classmethod
    def stand(cls, **connect_kwargs: Any) -> Any:
        return cls._once(lambda dog: dog._stand(), **connect_kwargs)

    @classmethod
    def sit(cls, **connect_kwargs: Any) -> Any:
        return cls._once(lambda dog: dog._sit(), **connect_kwargs)

    @classmethod
    def stop(cls, **connect_kwargs: Any) -> Any:
        return cls._once(lambda dog: dog._stop(), **connect_kwargs)

    @classmethod
    def forward(cls, speed: float = DEFAULT_SPEED_MPS, seconds: float = DEFAULT_SECONDS, *, stop: bool = True, **connect_kwargs: Any) -> Any:
        return cls._once(lambda dog: dog._forward(speed=speed, seconds=seconds, stop=stop), **connect_kwargs)

    @classmethod
    def backward(cls, speed: float = DEFAULT_SPEED_MPS, seconds: float = DEFAULT_SECONDS, *, stop: bool = True, **connect_kwargs: Any) -> Any:
        return cls._once(lambda dog: dog._backward(speed=speed, seconds=seconds, stop=stop), **connect_kwargs)

    @classmethod
    def yaw(cls, speed: float = DEFAULT_YAW_RATE, seconds: float = DEFAULT_SECONDS, *, stop: bool = True, **connect_kwargs: Any) -> Any:
        return cls._once(lambda dog: dog._yaw(speed=speed, seconds=seconds, stop=stop), **connect_kwargs)

    @classmethod
    def rotate(cls, angle: float = 90.0, speed: float = DEFAULT_YAW_RATE, *, stop: bool = True, **connect_kwargs: Any) -> Any:
        return cls._once(lambda dog: dog._rotate(angle=angle, speed=speed, stop=stop), **connect_kwargs)

    @classmethod
    def turn_left(cls, angle: float = 45.0, speed: float = DEFAULT_YAW_RATE, *, stop: bool = True, **connect_kwargs: Any) -> Any:
        return cls._once(lambda dog: dog._turn_left(angle=angle, speed=speed, stop=stop), **connect_kwargs)

    @classmethod
    def left(cls, angle: float = 45.0, speed: float = DEFAULT_YAW_RATE, *, stop: bool = True, **connect_kwargs: Any) -> Any:
        return cls.turn_left(angle=angle, speed=speed, stop=stop, **connect_kwargs)

    @classmethod
    def turn_right(cls, angle: float = 45.0, speed: float = DEFAULT_YAW_RATE, *, stop: bool = True, **connect_kwargs: Any) -> Any:
        return cls._once(lambda dog: dog._turn_right(angle=angle, speed=speed, stop=stop), **connect_kwargs)

    @classmethod
    def right(cls, angle: float = 45.0, speed: float = DEFAULT_YAW_RATE, *, stop: bool = True, **connect_kwargs: Any) -> Any:
        return cls.turn_right(angle=angle, speed=speed, stop=stop, **connect_kwargs)

    @classmethod
    def pitch(cls, speed: float = DEFAULT_PITCH_RATE, seconds: float = 0.5, *, stop: bool = True, hz: float = 20.0, **connect_kwargs: Any) -> Any:
        return cls._once(lambda dog: dog._pitch(speed=speed, seconds=seconds, stop=stop, hz=hz), **connect_kwargs)

    @classmethod
    def camera_pitch(cls, angle: float = 10.0, speed: float = DEFAULT_PITCH_RATE, *, stop: bool = True, **connect_kwargs: Any) -> Any:
        return cls._once(lambda dog: dog._camera_pitch(angle=angle, speed=speed, stop=stop), **connect_kwargs)

    @classmethod
    def look_up(cls, angle: float = 10.0, speed: float = DEFAULT_PITCH_RATE, *, stop: bool = True, **connect_kwargs: Any) -> Any:
        return cls._once(lambda dog: dog._look_up(angle=angle, speed=speed, stop=stop), **connect_kwargs)

    @classmethod
    def look_down(cls, angle: float = 10.0, speed: float = DEFAULT_PITCH_RATE, *, stop: bool = True, **connect_kwargs: Any) -> Any:
        return cls._once(lambda dog: dog._look_down(angle=angle, speed=speed, stop=stop), **connect_kwargs)

    @classmethod
    def emergency_stop(cls, reason: str = "Agentech emergency stop", **connect_kwargs: Any) -> Any:
        return cls._once(lambda dog: dog._emergency_stop(reason=reason), **connect_kwargs)

    @classmethod
    def get_status(cls, **connect_kwargs: Any) -> dict[str, Any]:
        return cls._once(lambda dog: dog._get_status(), **connect_kwargs)

    @classmethod
    def capture_image(cls, output: str | Path = "agentech_capture.jpg", source: str = "default", **connect_kwargs: Any) -> str | None:
        return cls._once(lambda dog: dog._capture_image(output=output, source=source), **connect_kwargs)

    @classmethod
    def say(cls, text: str, **connect_kwargs: Any) -> dict[str, str]:
        return cls._once(lambda dog: dog._say(text), **connect_kwargs)

    @classmethod
    def run_sequence(cls, actions: Iterable[dict[str, Any]], **connect_kwargs: Any) -> list[Any]:
        return cls._once(lambda dog: dog._run_sequence(actions), **connect_kwargs)
