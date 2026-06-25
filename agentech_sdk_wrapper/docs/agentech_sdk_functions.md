# Agentech SDK 函数说明

目标导入方式：

```python
import agentech as agt
```

同步用户使用 `agt.Dog()`，高级用户可以使用 `agt.AsyncDog()` 并对动作
`await dog.agt.<action>()`。

## 运行模式

| 模式 | 是否连接真机 | Windows 可用 | 说明 |
| --- | --- | --- | --- |
| `dry_run` | 否 | 是 | 默认无 `key` 时进入；不 sleep、不移动，只返回动作计算结果。 |
| `simulation` | 否 | 是 | 本地维护简化位置和朝向状态，不连接机器人。 |
| `hardware` | 是 | 默认否 | 需要 `key` 或 `AGENTECH_TARGET`、安装 `ff_sdk`、并显式设置 `allow_hardware=True` 或 `AGENTECH_ALLOW_HARDWARE=1`。 |

默认选择策略：

- 无 `key`：`dry_run`。
- Windows：默认 `dry_run` 或 `simulation`，不自动进入 `hardware`。
- 有 `key` 且配置允许硬件，并且运行环境支持：`hardware`。

## 安全速度配置

当前没有在原项目中找到独立的算法组速度参数文件；本 wrapper 在
`agentech/config.py` 中预留并填入本次提供的参数：

- `THEORETICAL_MAX_FORWARD_SPEED_MPS = 2.37`
- `SAFE_MAX_FORWARD_SPEED_RATIO = 0.95`
- `SAFE_MAX_FORWARD_SPEED_MPS = 2.37 * 0.95`
- `DEFAULT_SLOW_FORWARD_SPEED_MPS = 0.3`

TODO：如果算法组后续要求从统一参数文件读取，请把
`THEORETICAL_MAX_FORWARD_SPEED_MPS` 改为真实来源。若该值为空，wrapper 会使用
保守值 `0.5 m/s` 作为 `safe_max_speed`。

## 统一返回值

所有动作返回：

```python
from dataclasses import dataclass

@dataclass
class ActionResult:
    status: str
    action: str
    result: dict
    trace_id: str | None = None
```

`status` 常见值：

- `ok`：动作执行或模拟成功。
- `unsupported`：能力不存在，例如本地模式下 `capture_image()` 或 `say()`。

## `Dog(key=None, mode=None, ...)`

创建同步 SDK 对象。测试阶段 `key` 可不传。未来后台上传代码后，可自动注入
`key="encrypted_key"`，由后台映射到指定机器狗。

参数：

- `key`: 可选，加密机器狗标识。当前硬件模式下会作为 target 的最后兜底。
- `mode`: 可选，`dry_run` / `simulation` / `hardware`。
- `target`: 可选，底层 `ff_sdk.connect(target, ...)` 使用的目标名。
- `allow_hardware`: 可选，硬件模式安全开关。

真实移动：

- `dry_run` / `simulation`：不会。
- `hardware`：会，取决于动作。

## `AsyncDog(...)`

异步版本。参数与 `Dog` 相同。示例：

```python
import asyncio
import agentech as agt

async def main():
    d = agt.AsyncDog(mode="dry_run")
    await d.agt.stand()
    await d.close()

asyncio.run(main())
```

## `stand()`

让机器人站立。

参数：无。

返回：`ActionResult(action="stand")`。

模式：

- `dry_run`：记录动作，不移动。
- `simulation`：记录动作，不移动。
- `hardware`：调用 `await sess.motion.stand()`，会真实改变机器人姿态。

## `sit()`

让机器人坐下/趴下的兼容封装。

参数：无。

返回：`ActionResult(action="sit")`。

硬件适配顺序：尝试 `motion.sit()`，然后 `motion.do_preset("sit")`，然后
`motion.do_preset("lie_down")`，最后尝试 `motion.damping()`。

真实移动：仅 `hardware` 会真实改变机器人姿态。

## `set_forward_speed(speed_mps)`

设置后续 `move_forward()` / `move_backward()` 使用的线速度。

参数：

- `speed_mps`: 米/秒，必须 `> 0` 且 `<= safe_max_speed`。

返回：`ActionResult(action="set_forward_speed")`。

真实移动：不会，只更新 SDK 内部速度。

抛错：

- `ValueError`: 速度小于等于 0，或超过安全上限。

## `move_forward(value, unit="s")`

向前有界移动。不做自动避障、路径规划、目标追踪。

参数：

- `value`: 移动值，必须 `> 0`。
- `unit="s"`: `value` 表示持续秒数。
- `unit="m"`: `value` 表示距离米数，内部按当前速度换算持续时间：
  `duration_s = value / current_forward_speed_mps`。

返回：`ActionResult(action="move_forward")`，`result` 包含 `duration_s`、
`distance_m`、`speed_mps`。

模式：

- `dry_run`：不 sleep、不移动，只返回换算结果。
- `simulation`：更新本地简化位姿，不移动真机。
- `hardware`：调用 `motion.cmd_vel(linear=speed, angular=0)`，等待有界时间，
  然后调用 `motion.stop()`，会真实移动。

抛错：

- `ValueError`: 非法 `unit` 或 `value <= 0`。
- `SafetyError`: 已触发 `emergency_stop()`。

## `move_backward(value, unit="s")`

向后有界移动。语义与 `move_forward()` 相同，但线速度为负。

真实移动：仅 `hardware` 会真实移动机器狗。

## `turn_left(angle_deg)`

向左有界转动指定角度。

参数：

- `angle_deg`: 角度，必须 `> 0`。

内部转换：

- `duration_s = angle_deg / DEFAULT_YAW_RATE_DEG_S`
- `angular_rad_s = radians(DEFAULT_YAW_RATE_DEG_S)`

真实移动：仅 `hardware` 会调用 `cmd_vel(angular=...)` 真实转向。

## `turn_right(angle_deg)`

向右有界转动指定角度。

参数：

- `angle_deg`: 角度，必须 `> 0`。

内部调用：`rotate(-angle_deg)`。

真实移动：仅 `hardware` 会真实转向。

## `rotate(angle_deg)`

有界旋转。正数左转，负数右转。

参数：

- `angle_deg`: 非 0 角度。

返回：`ActionResult(action="rotate")`，`result` 包含方向、角速度和持续时间。

不做目标对齐；只是角速度加持续时间的有界动作。

## `stop()`

普通停止。

参数：无。

返回：`ActionResult(action="stop")`。

硬件模式调用 `await sess.motion.stop()`。`stop()` 不是 `emergency_stop()`，不会进入
后续动作阻断状态。

## `emergency_stop(reason="user")`

紧急停止。

参数：

- `reason`: 停止原因。

返回：`ActionResult(action="emergency_stop")`。

行为：

- 触发后，本 wrapper 会设置 `emergency_stop_active=True`。
- 后续 `stand()`、`sit()`、`move_forward()`、`move_backward()`、`turn_left()`、
  `turn_right()`、`rotate()` 会被阻止。
- 当前没有暴露 reset API；需要先定义操作员确认和复位策略。

硬件模式调用 `await sess.e_stop(reason=..., source="agentech")`，会真实触发急停。

## `get_status()`

读取状态快照。

参数：无。

返回：`ActionResult(action="get_status")`，包含当前模式、当前速度、安全上限、
急停状态，以及底层状态。

模式：

- `dry_run`：返回本地事件计数和速度状态。
- `simulation`：额外返回简化 `pose`。
- `hardware`：尝试调用 `sess.state.status()`、`battery()`、`pose()`。

真实移动：不会。

## `capture_image()`

如果底层支持，则抓取图像。

参数：无。

返回：

- 支持：`ActionResult(status="ok", action="capture_image")`。
- 不支持：`ActionResult(status="unsupported", action="capture_image")`。

本地模式不会访问摄像头。硬件模式会尝试常见接口：
`session.camera.capture_image()` / `capture()` / `snapshot()` / `read()`。

真实移动：不会。

## `say(text)`

如果底层支持语音，则播放文本。

参数：

- `text`: 要说的文本。

返回：

- 支持：`ActionResult(status="ok", action="say")`。
- 不支持：`ActionResult(status="unsupported", action="say")`。

硬件模式尝试 `session.audio.say()`、`session.speech.say()`、`session.tts.say()` 或
对应 `speak()`。

真实移动：不会。

## `close()`

关闭连接/同步后台事件循环。

同步写法：

```python
d = agt.Dog()
try:
    d.agt.stand()
finally:
    d.close()
```

异步写法：

```python
d = agt.AsyncDog()
try:
    await d.agt.stand()
finally:
    await d.close()
```
