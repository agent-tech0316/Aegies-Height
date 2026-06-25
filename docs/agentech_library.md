# Agentech Python Library

`agentech` is a simple wrapper over the FF Aegis SDK for students and web-submitted robot dog code.

## Install

For local development from this repository:

```bash
cd Aegies-Height
pip install -e .
```

For a robot or Linux machine using the bundled FF SDK wheel:

```bash
cd Aegies-Height
pip install wheels/ff_sdk-0.1.0a1-cp310-cp310-linux_x86_64.whl
pip install -e .
```

On the robot itself, install the `linux_aarch64` wheel instead:

```bash
pip install wheels/ff_sdk-0.1.0a1-cp310-cp310-linux_aarch64.whl
pip install -e .
```

Later, after publishing the package, students should be able to install it with:

```bash
pip install agentech
```

For MuJoCo simulation preview support:

```bash
pip install -e ".[sim]"
```

MuJoCo preview support uses the Faraday Future Aegis URDF/MuJoCo assets under `agentech/assets/aegis`, including a floating-root preview model for local simulation.

## One-line commands

```python
from agentech import Agentech

Agentech.forward(speed=0.3, seconds=1)
Agentech.backward(speed=0.2, seconds=1)
Agentech.left(angle=45)
Agentech.right(angle=45)
Agentech.turn_left(angle=45)
Agentech.turn_right(angle=45)
Agentech.rotate(angle=90)
Agentech.yaw(speed=0.35, seconds=1)
Agentech.stand()
Agentech.look_up(angle=15)
Agentech.capture_image(output="height_photo.jpg")
Agentech.look_down(angle=15)
Agentech.capture_image(output="height_bottom.jpg")
Agentech.stop()
```

## Recommended multi-step style

```python
from agentech import Agentech

with Agentech.robot(dry_run=True) as dog:
    dog.stand()
    dog.forward(speed=0.25, seconds=1.0)
    dog.left(angle=45)
    dog.right(angle=45)
    dog.look_up(angle=15)
    dog.capture_image(output="height_photo.jpg")
    dog.look_down(angle=15)
    dog.capture_image(output="height_bottom.jpg")
    dog.say("Hello")
    dog.stop()
```

## Action card mapping

| Action card | Agentech call | FF SDK grounding |
| --- | --- | --- |
| `aegis.walk_forward` | `Agentech.forward(speed, seconds)` | `motion.cmd_vel(linear=+speed)` |
| `aegis.walk_backward` | `Agentech.backward(speed, seconds)` | `motion.cmd_vel(linear=-speed)` |
| `aegis.turn_left` | `Agentech.turn_left(angle)` | `motion.cmd_vel(angular=+speed)` |
| `aegis.turn_right` | `Agentech.turn_right(angle)` | `motion.cmd_vel(angular=-speed)` |
| `aegis.rotate` | `Agentech.rotate(angle)` | signed yaw command |
| `aegis.attitude_control` | `Agentech.look_up(angle)` / `Agentech.look_down(angle)` | `motion.attitude_control(pitch_vel=...)` streamed at 20 Hz; positive pitch tilts up, negative pitch tilts down |
| `aegis.stop` | `Agentech.stop()` | `motion.stop()` |
| `aegis.stand` | `Agentech.stand()` | `motion.stand()` |
| `aegis.sit` | `Agentech.sit()` | `motion.sit()` or `do_preset("lie_down")` |
| `aegis.emergency_stop` | `Agentech.emergency_stop()` | `session.e_stop()` |
| `aegis.get_status` | `Agentech.get_status()` | `state.status()`, `state.battery()`, `state.pose()` |
| `aegis.capture_image` | `Agentech.capture_image()` | `vision.frame()` |
| `aegis.say` | `Agentech.say(text)` | text accepted now, audio adapter later |
| `aegis.run_sequence` | `Agentech.run_sequence(actions)` | ordered wrapper calls |

Keep `dry_run=True` while developing on Windows or Mac, then run on Linux or directly on the robot dog for hardware control.
