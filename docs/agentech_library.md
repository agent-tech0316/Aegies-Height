# Agentech Python Library

`agentech` is the simple Python layer for controlling the Aegis robot dog. The goal is that a student can write one readable line:

```python
Agentech.forward()
Agentech.look_up()
Agentech.capture_image()
```

The library hides the lower-level FF SDK calls, safety clamps values, and still lets advanced users pass speed, seconds, angle, and robot connection settings when needed.

Important: `Agentech.forward()` is a real robot command by default. If the FF SDK is installed and the machine can reach the robot, it connects to the normal robot hotspot host (`192.168.234.1`) with the Aegis EDU / Ultra variant (`zsl-1`), stands the robot with `motion.stand()`, waits one second for the body to settle, sends `motion.cmd_vel(linear=+speed, angular=0.0)`, waits for the requested time, then stops. Use `dry_run=True` only when you intentionally want practice code that does not move hardware.

## Install

Install from GitHub today:

```bash
pip install git+https://github.com/agent-tech0316/Aegies-Height.git
```

For local development from this repository:

```bash
cd Aegies-Height
pip install -e .
```

For MuJoCo preview support:

```bash
pip install -e ".[sim]"
```

For real robot hardware, install the FF SDK wheel first, then install Agentech:

```bash
pip install wheels/ff_sdk-0.1.0a1-cp310-cp310-linux_x86_64.whl
pip install -e .
```

On the robot itself, use the `linux_aarch64` FF SDK wheel.

## First Script

```python
from agentech import Agentech

Agentech.stand()
Agentech.forward()
Agentech.left()
Agentech.look_up()
Agentech.capture_image(output="top.jpg")
Agentech.look_down()
Agentech.capture_image(output="bottom.jpg")
Agentech.stop()
```

Every one-line call opens a robot session, runs the command, then closes safely. That is easiest for beginners.

For a real robot on a known IP address:

```python
from agentech import Agentech

Agentech.forward(host="192.168.234.1", speed=0.2, seconds=1)
```

That one line means:

```python
await dog.motion.stand()
await asyncio.sleep(1)
await dog.motion.cmd_vel(linear=0.2, angular=0.0)
await asyncio.sleep(1)
await dog.motion.stop()
```

## Student Submission / Robot Hotspot Workflow

The student code should stay simple. For example, `student_forward.py` can be only:

```python
from agentech import Agentech

Agentech.forward()
```

The deployment workflow does the rest:

1. connect the computer to the robot hotspot
2. copy the student Python file to the robot over SSH
3. run the file on the robot with the FF SDK installed
4. the Agentech library stands the robot, waits, moves forward, stops, and closes the session

Command-line runner:

```bash
export ROBOT_PASSWORD=...
python scripts/run_agentech_on_robot.py examples/student_forward.py --host 192.168.234.1
```

That runner uploads the local `agentech` package to `/tmp/agentech_runtime`, uploads the student script to `/tmp/agentech_student.py`, sets `PYTHONPATH=/tmp/agentech_runtime`, sets `FF_SDK_D1_VARIANT=zsl-1`, disables dry-run, and runs `python3 /tmp/agentech_student.py` on the robot.

For real movement to work, the robot runtime still needs the FF SDK wheel installed and the robot must be reachable over the hotspot/SSH network. If those two things are true, `Agentech.forward()` sends the real FF SDK movement command.

## Recommended Session Style

Use a session when running several commands together. This keeps one robot connection open and makes longer programs cleaner.

```python
from agentech import Agentech

with Agentech.robot(host="192.168.234.1", dry_run=False) as dog:
    dog.stand()
    dog.forward(speed=0.25, seconds=1.0)
    dog.left(angle=45)
    dog.look_up(angle=15)
    dog.capture_image(output="height_top.jpg")
    dog.look_down(angle=15)
    dog.capture_image(output="height_bottom.jpg")
    dog.stop()
```

Use `dry_run=True` while writing code on a laptop. Use `dry_run=False` or omit it when running on the real robot with the FF SDK installed.

Movement commands automatically stand first:

```python
Agentech.forward()
Agentech.backward()
Agentech.left()
Agentech.right()
Agentech.yaw()
```

Each one follows the same formal sequence:

1. connect to the robot
2. stand up
3. wait for `stand_wait=1.0`
4. run the motion command
5. stop
6. close the session

Advanced users can set `auto_stand=False` or `stand_wait=0` when they are already managing posture themselves.

## Easy Function Reference

| Function | Easiest call | Parameters | What it does |
| --- | --- | --- | --- |
| `stand` | `Agentech.stand()` | none | Stands the dog up so it is ready to move. |
| `sit` | `Agentech.sit()` | none | Returns the dog to a safe sitting or lie-down posture. |
| `forward` | `Agentech.forward()` | `speed=0.3`, `seconds=1.0` | Walks forward. Speed is meters per second. |
| `backward` | `Agentech.backward()` | `speed=0.3`, `seconds=1.0` | Walks backward. Pass a positive speed; the library handles direction. |
| `left` | `Agentech.left()` | `angle=45`, `speed=0.35` | Turns left by degrees. This is the simple alias students should use. |
| `right` | `Agentech.right()` | `angle=45`, `speed=0.35` | Turns right by degrees. This is the simple alias students should use. |
| `turn_left` | `Agentech.turn_left()` | `angle=45`, `speed=0.35` | Same as `left`, with a more explicit name. |
| `turn_right` | `Agentech.turn_right()` | `angle=45`, `speed=0.35` | Same as `right`, with a more explicit name. |
| `rotate` | `Agentech.rotate(angle=90)` | `angle=90`, `speed=0.35` | Rotates by a signed angle. Positive is left, negative is right. |
| `yaw` | `Agentech.yaw(speed=0.35, seconds=1)` | `speed`, `seconds` | Advanced direct yaw-rate control. Positive turns left, negative turns right. |
| `look_up` | `Agentech.look_up()` | `angle=10`, `speed=0.12` | Tilts the Aegis body/camera up for height-photo workflows. |
| `look_down` | `Agentech.look_down()` | `angle=10`, `speed=0.12` | Tilts the Aegis body/camera down for height-photo workflows. |
| `camera_pitch` | `Agentech.camera_pitch(angle=-10)` | `angle`, `speed=0.12` | Signed tilt. Positive looks up; negative looks down. |
| `pitch` | `Agentech.pitch(speed=0.12, seconds=0.5)` | `speed`, `seconds`, `hz=20` | Advanced direct pitch-velocity control. |
| `capture_image` | `Agentech.capture_image("photo.jpg")` | `output`, `source="default"` | Captures one camera frame and saves it. |
| `get_status` | `Agentech.get_status()` | none | Reads status, battery, pose, and emergency stop state. |
| `say` | `Agentech.say("Hello")` | `text` | Accepts a short message. Audio adapter can be connected later. |
| `stop` | `Agentech.stop()` | none | Stops current motion. |
| `emergency_stop` | `Agentech.emergency_stop()` | `reason` | Latches an emergency stop condition. |
| `run_sequence` | `Agentech.run_sequence([...])` | list of actions | Runs an ordered list of simple commands. |

## Parameter Rules

| Parameter | Used by | Default | Safe range | Meaning |
| --- | --- | --- | --- | --- |
| `speed` | `forward` | `0.3` | `0.0` to `2.37` | Forward walking speed in meters per second. |
| `speed` | `backward` | `0.3` | `0.0` to `2.365` | Backward walking speed in meters per second. |
| `seconds` | walking, yaw, pitch | `1.0` | `0.0` to `10.0` | How long to hold the command. |
| `stand_wait` | all movement commands | `1.0` | `0.0` to `10.0` | How long to wait after automatic stand before motion starts. |
| `angle` | turn, rotate, look up/down | `45` for turns, `10` for tilt | turns: `-360` to `360`; look up: `0` to `19`; look down: `0` to `21` | Human-readable degrees, using the report_zh pitch limit. |
| `speed` | `left`, `right`, `rotate` | `0.35` | `0.05` to `2.09` | Yaw rate used to estimate turn duration. |
| `speed` | `look_up`, `look_down`, `camera_pitch` | `0.12` | `0.03` to `0.5` | Pitch velocity in radians per second. |
| `hz` | `pitch` | `20` | `1` to `50` | How often attitude control is resent. |
| `output` | `capture_image` | `agentech_capture.jpg` | any local path | File path where the image is saved. |

## Height Photo Example

This is the simple version for the height-measurement workflow:

```python
from agentech import Agentech

with Agentech.robot(host="192.168.234.1") as dog:
    dog.stand()
    dog.look_up(angle=15)
    dog.capture_image(output="top.jpg")
    dog.look_down(angle=15)
    dog.capture_image(output="bottom.jpg")
    dog.stop()
```

`look_up` and `look_down` use the FF SDK attitude command:

```python
motion.attitude_control(pitch_vel=...)
```

The preview shows this as a body/camera tilt, like the real Aegis height demo. The dog should tilt; the observer camera should not be the thing moving.

## Aegis v0.1 Limits From report_zh

| Capability | Limit |
| --- | --- |
| Forward speed | `0.0` to `2.37 m/s` |
| Backward speed | `0.0` to `2.365 m/s` |
| Lateral speed | `0.0` to `0.78 m/s` |
| Linear acceleration | about `2.5 m/s^2` |
| Turn/yaw rate | up to `2.09 rad/s` (`120 deg/s`) |
| Slow yaw rate | `1.05 rad/s` (`60 deg/s`) |
| Look up / forward pitch | `0` to `19 deg` |
| Look down / backward pitch | `0` to `21 deg` |
| Roll angle | up to `28 deg` |
| Body Z range | `-0.06 m` to `+0.11 m` |
| Gait step length | `0.669 m` |
| Path tracking error | `7-8%` |

## Action Card Mapping

| Action card | Agentech call | FF SDK grounding |
| --- | --- | --- |
| `aegis.walk_forward` | `Agentech.forward(speed, seconds)` | `motion.cmd_vel(linear=+speed, angular=0.0)` |
| `aegis.walk_backward` | `Agentech.backward(speed, seconds)` | `motion.cmd_vel(linear=-speed, angular=0.0)` |
| `aegis.turn_left` | `Agentech.left(angle)` / `Agentech.turn_left(angle)` | `motion.cmd_vel(angular=+speed)` |
| `aegis.turn_right` | `Agentech.right(angle)` / `Agentech.turn_right(angle)` | `motion.cmd_vel(angular=-speed)` |
| `aegis.rotate` | `Agentech.rotate(angle)` / `Agentech.yaw(speed, seconds)` | signed yaw command |
| `aegis.attitude_control` | `Agentech.look_up(angle)` / `Agentech.look_down(angle)` | `motion.attitude_control(pitch_vel=...)` streamed at 20 Hz |
| `aegis.stop` | `Agentech.stop()` | `motion.stop()` |
| `aegis.stand` | `Agentech.stand()` | `motion.stand()` |
| `aegis.sit` | `Agentech.sit()` | `motion.sit()` or `do_preset("lie_down")` |
| `aegis.emergency_stop` | `Agentech.emergency_stop()` | `session.e_stop()` |
| `aegis.get_status` | `Agentech.get_status()` | `state.status()`, `state.battery()`, `state.pose()` |
| `aegis.capture_image` | `Agentech.capture_image()` | `vision.frame()` |
| `aegis.say` | `Agentech.say(text)` | text adapter now; audio adapter later |
| `aegis.run_sequence` | `Agentech.run_sequence(actions)` | ordered wrapper calls |

## Run Sequence Example

```python
from agentech import Agentech

Agentech.run_sequence([
    {"action": "stand"},
    {"action": "forward", "params": {"speed": 0.25, "seconds": 1}},
    {"action": "left", "params": {"angle": 45}},
    {"action": "look_up", "params": {"angle": 15}},
    {"action": "capture_image", "params": {"output": "top.jpg"}},
    {"action": "stop"},
])
```
