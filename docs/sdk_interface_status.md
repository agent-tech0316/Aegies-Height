# SDK Interface Status and Height-System Known/Unknowns

This document summarizes what we already know from the repo, what is partially
known, and what we still need from FF/Faraday Future for a complete interface
checklist.

## Current Project Context

- Robot: D1 / Aegis robot dog path. The target names used in code are usually
  `D1-DEMO`, `D1-XG03`, or an explicit robot host like `192.168.234.1`.
- Pi role: Raspberry Pi runs the height pipeline, depth sensor code, camera
  capture/vision code, and trigger logic.
- Robot camera: OpenCV can read the robot RTSP stream when the Pi can reach the
  robot network. The stream URL used in our scripts is:
  `rtsp://192.168.234.1:8554/test`.
- Depth sensor: HC-SR04 style ultrasonic sensor through `gpiozero`.
- External pitch sensor: Codey Rocky can provide a pitch angle over USB serial.
  The Pi reads it from a port like `/dev/ttyUSB0` at `115200` baud.
- Current best camera calibration:
  `charuco_runs/latest/charuco_camera_calibration_refined.json`
  - accepted images: 23
  - RMS reprojection error: about `0.174 px`
  - mean point error: about `0.150 px`
  - horizontal FOV: about `100.72 deg`
  - vertical FOV: about `68.34 deg`

## FF SDK Checklist

| Checklist item | Status | What we know now | What we still need from FF |
| --- | --- | --- | --- |
| Velocity Control | Known | Python uses `motion.cmd_vel(linear, angular, lateral)`. C++ uses `move(vx, vy, yaw_rate)`. Repo examples also include UDP/D1 walk scripts. | Official limits, acceleration behavior, and exact backend differences between Aegis SDK and dog_task fallback. |
| Gait Control | Partial | We know `stand()`, `lie_down`/`lieDown()`, `damping()`, presets like `jump`, `front_jump`, `backflip`, `shake_hand`, `two_leg_stand`, and `crawl` for some variants. | Complete gait/mode list, exact controller mode equivalents such as `START+B`, and which modes are supported on our hardware/firmware. |
| Pose Control | Partial | D1 supports `motion.attitude_control(roll_vel, pitch_vel, yaw_vel, height_vel)`. Pitch/yaw are continuous. Roll/height may become discrete pulses under dog_task fallback. | Units-to-degrees mapping, true pitch speed in deg/sec, hard limits, frame definitions, and whether attitude control requires a mode switch. |
| Camera Stream | Partial | RTSP stream works outside the SDK at `rtsp://192.168.234.1:8554/test`. OpenCV reads it when networking is correct. | Official stream URL/API, stream codec, resolution, latency, reconnection behavior, and whether SDK exposes camera frames directly. |
| IMU Data | Partial | SDK exposes pose-like telemetry: Python `state.pose()`, C++ `rpy()`, `quaternion()`, `bodyVelocity()`. We also added external Codey pitch over USB. | Official IMU frame, units, timestamping, whether values represent body, camera, or fused pose, and how stable pitch is during attitude control. |
| Odometry | Partial | C++ exposes `position()` and `bodyVelocity()`. Python docs mention `state.pose()`. | Origin/reset behavior, coordinate frame, drift expectations, and whether there is a ROS2 odom topic/API. |
| Battery State | Known | Python `state.battery()` and C++ `battery()` exist. Example scripts are in `examples/state/read_battery.py`. | Confirm exact fields on our robot, especially voltage/current/charging validity. |
| Charging State | Partial | Battery objects may expose `is_charging`, but we have not proven a separate charging/dock state. | Official charging state API and whether it works off-dock/on-dock. |
| Event Callback | Partial | SDK docs show e-stop callback support. Our RT button logic is custom UDP/controller forwarding, not a proven official SDK callback. | Official controller button event API, RT/LT trigger events, mode-change events, and state-change callbacks. |
| Dock Interface | Unknown | No dock API found in this repo. | Complete dock API, docking state, charging handshake, and docking commands. |
| ROS2 Support | Partial | Robot processes show ROS2/dog_task/perception/eCAL internally. Repo does not document a public ROS2 API. | Supported ROS2 topics/services/actions, message types, launch requirements, and whether external nodes are supported. |
| Python SDK | Known | `ff_sdk 0.1.0a0` exists. Python 3.10 is required. Linux is required for true robot control. Windows/Mac dry-run only. | Official install package/source, version compatibility, and long-term API stability. |
| C++ SDK | Known | C++ header/library exist under `cpp/`. API includes connect, stand, move, attitude, presets, battery, control mode, pose, and joints. | Official ABI/version support and examples for our exact robot model. |
| OTA Interface | Unknown | No OTA API found in this repo. | Firmware/software update API, safety rules, and rollback behavior. |
| Expansion Port API | Unknown | Our Pi/USB/GPIO sensors are project-side additions. No official robot expansion-port API found. | Physical/electrical/API spec for expansion ports, power limits, serial/CAN/USB access, and supported payloads. |
| Time Sync API | Unknown | No time sync API found in the repo. | Clock sync method, timestamp source, network time behavior, and camera/IMU/frame timestamp alignment. |
| Video Stream API | Partial | Video is available through RTSP/OpenCV. Calibration and height code consume frames through OpenCV. | Official video API, camera metadata, intrinsic/extrinsic parameters, and synchronized frame timestamps. |

## What We Already Know in Our Height Code

### Person Detection

- Main file: `examples/vision/human_height_live.py`
- Uses OpenCV + NumPy + YOLO ONNX to detect people.
- Draws the red person box and confidence score.
- Chooses a person detection, checks whether the person is in the acceptable
  gate, then decides whether to continue, move, or reject.
- Important areas:
  - person processing starts around `process_once(...)`
  - YOLO detection and person selection are around lines `970-1010`
  - output/status image annotation is around lines `334-386`

### Yellow Box / Center Gate

- In `examples/vision/human_height_live.py`, the center gate is based on
  `--center-tolerance-ratio`.
- In `examples/vision/rt_person_tilt_sequence.py`, the larger yellow box uses
  `--big-box-ratio`.
- Meaning:
  - red box = detected person
  - yellow vertical lines = acceptable region for the person center
  - tighter center lines = where the person is considered centered enough
  - if the person is outside the large yellow box, the system should not run
    the tilt capture yet

### Depth Sensor

- Main read logic is in `examples/vision/height_calculator.py`.
- Live height logic is in `examples/vision/human_height_live.py`.
- HC-SR04 reading uses `gpiozero.DistanceSensor`.
- The code supports background learning and rejects readings that look like
  wall/background or non-human objects.
- `--depth-sensor-behind-camera-cm` and `--depth-sensor-above-camera-cm`
  correct the ultrasonic distance because the sensor is mounted behind and
  above the camera. Current measured mount: 12 cm behind, 12 cm above.
  The live code uses:
  `camera_distance_cm = sqrt(sensor_distance_cm^2 - above_cm^2) - behind_cm`.
- Important areas:
  - raw HC-SR04 reading is in `height_calculator.py`
  - camera/sensor distance correction is around `human_height_live.py:198-205`
  - non-human/background distance rejection is around `human_height_live.py:203-225`
  - multiple depth bursts/median reading are around `human_height_live.py:243-292`

### Camera Calibration

- Current best file:
  `charuco_runs/latest/charuco_camera_calibration_refined.json`
- This is our strongest calibration so far.
- It is good enough for middle-frame height work, especially if the robot
  centers the person before estimating height.
- Side coverage is weaker than center coverage, so the safest workflow is:
  detect person, move/turn until person is in the middle area, then run tilt
  captures.

### Robot Tilt / Pitch

- SDK attitude control file:
  `examples/motion/attitude.py`
- RT-triggered tilt flow:
  `examples/vision/rt_person_tilt_sequence.py`
- Robot motion server:
  `scripts/robot_motion_server.py`
- Codey pitch reader:
  `examples/vision/read_codey_pitch.py`
  and `examples/vision/codey_pitch.py`
- Known behavior:
  - `attitude_control(pitch_vel=...)` is the SDK method for tilt up/down.
  - It must be sent repeatedly, like holding a joystick.
  - The robot should already be standing.
  - Our trigger/tilt flow is intended to avoid damping and return to neutral
    standing.
- Still needs final proof:
  - exact pitch degrees per second on the mounted robot
  - whether Codey pitch agrees with visual/camera pitch
  - best tilt amount and settle time before taking each image

### RT Button Trigger

- RT trigger flow is in `examples/vision/rt_person_tilt_sequence.py`.
- It waits for a UDP/controller event, then checks camera/person position.
- Intended behavior:
  1. robot is already standing
  2. background is learned
  3. RT is pressed
  4. camera frame is checked
  5. if a person is in the large yellow box, center the person
  6. tilt up, pause, capture
  7. return neutral
  8. tilt down, pause, capture
  9. return neutral standing
  10. do not call damping

## What We Do Not Know Yet

- The exact official controller event API for RT/LT/buttons.
- The exact SDK equivalent of controller mode switching such as `START+B`.
- Whether `attitude_control` is always available through the Aegis backend on
  our robot, or whether it sometimes falls back to dog_task.
- The exact mapping from `pitch_vel` and hold time to real camera pitch degrees.
- Whether Codey pitch is rigidly aligned enough to represent camera pitch after
  mounting.
- Whether ultrasonic readings stay reliable when the person is not perfectly in
  the beam center.
- The official robot camera metadata: frame timestamp, lens intrinsics,
  distortion, and whether stream frames are synchronized with IMU/pose.
- Whether charging, dock, OTA, expansion port, and time sync APIs exist in the
  SDK we have.

## Main Risks for Height Accuracy

- The ultrasonic sensor cannot classify objects by itself. It only returns the
  nearest echo in its cone. Human/non-human filtering must come from camera
  detection plus geometry.
- The depth sensor is currently measured as about 12 cm behind and 12 cm above
  the camera. The software corrects those offsets, but it does not fix lateral
  misalignment. The sensor must physically point at the same target area as the
  camera center.
- The robot camera is wide angle. Calibration is strong in the middle, but the
  safest final product should center the person before height calculation.
- Height accuracy depends on three things being correct at the same time:
  calibrated camera, correct pitch angle, and correct human distance.

## Concrete Questions to Send FF

1. Please provide the complete SDK interface document for D1/Aegis covering:
   velocity, gait, pose/attitude, camera/video stream, IMU, odometry, battery,
   charging, events, dock, ROS2, Python SDK, C++ SDK, OTA, expansion port, and
   time sync.
2. What is the official API for controller buttons/triggers, especially RT?
3. What is the official SDK equivalent of controller `START+B` mode?
4. For `motion.attitude_control`, what are the exact units, limits, frame
   definitions, and pitch degrees/second mapping?
5. Does `attitude_control` keep the robot standing, or can it trigger damping
   under any backend/failure condition?
6. What is the official robot camera stream URL/API, resolution, codec, latency,
   and reconnect behavior?
7. Are camera frames timestamped and synchronized with IMU/pose/odometry?
8. What ROS2 topics/services are supported for motion, camera, IMU, odometry,
   battery, and controller events?

## Files Worth Reading First

- `docs/getting_started.md` - SDK install, dry-run, config, basic APIs.
- `_incoming/ff_sdk_aegis_devkit_20260614/README.md` - devkit overview.
- `_incoming/ff_sdk_aegis_devkit_20260614/RELEASE_NOTES.md` - attitude control,
  fallback behavior, and new motion features.
- `examples/motion/attitude.py` - pitch/yaw/roll/height attitude example.
- `examples/d1/udp_walk.py` - D1 walk example.
- `examples/state/read_battery.py` - battery state example.
- `examples/state/watch_status.py` - status polling example.
- `cpp/README.md` - C++ SDK summary.
- `examples/vision/human_height_live.py` - live human/depth/status pipeline.
- `examples/vision/rt_person_tilt_sequence.py` - RT trigger, centering, tilt
  image capture pipeline.
- `examples/vision/height_calculator.py` - distance and height math helpers.
- `examples/vision/read_codey_pitch.py` - Codey pitch serial reader.
