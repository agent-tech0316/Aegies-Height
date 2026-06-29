# Aegis/D1 Dog Testing And Calibration Runbook

This is the command guide for the height-measurement project.

There are two separate work paths:

1. **Lens/FOV calibration**: use the wall grid and laser samples to estimate camera intrinsics, FOV, and distortion.
2. **Pitch/level height path**: use a same-height wall mark, radar/depth distance, and person pixels for the first working height demo.

Current recommendation: use the **pitch/level height path** for the next demo.
Keep the lens/FOV calibration data as a reference and later correction layer.

## 0. Project Files

Use these files:

```text
docs/dog_testing_runbook.md              # this guide
docs/camera_height_workflow.md           # height workflow overview
docs/accepted_laser_images_cleanup.md    # keep only accepted laser images and copy them off the robot
examples/vision/grid_laser_calibration.py # grid + laser calibration commands
examples/vision/height_calculator.py     # YOLO/distance/height helper commands
examples/vision/tilt_telemetry_probe.py  # tilt telemetry test, for later
../agentech_sdk/agentech_sdk/examples/d1/udp_walk.py # SDK walking demo from the vendor docs
../agentech_sdk/examples/d1/raw_zsibot_move.py       # project-specific raw movement test
../agentech_sdk/examples/d1/raw_zsibot_sequence.py   # project-specific raw movement sequence
models/yolov8n.onnx                      # YOLO model
requirements-vision.txt                  # Python vision dependencies
test_camera.jpg                          # sample grid image
```

## 1. Connect To The Dog

Known login for this dog:

```bash
ssh firefly@192.168.234.1
```

When prompted, enter the robot password provided with the dog.

If the dog has WiFi working, connect your laptop to the dog network and use the
command above.

If the dog does not have WiFi, use Ethernet:

1. Plug Ethernet into the dog and your router/switch, or directly into your laptop.
2. Find the dog IP address.
3. SSH into the dog.

If you have monitor/keyboard access to the dog, run this on the dog:

```bash
ip addr
```

Look for an address like:

```text
192.168.x.x
10.x.x.x
172.16.x.x
```

If the IP is still `192.168.234.1`, SSH from your laptop:

```bash
ssh firefly@192.168.234.1
```

If Ethernet gives the dog a different IP, keep the same username and replace the
IP:

```bash
ssh firefly@<robot-ip>
```

If SSH is not available, run the same commands directly on the dog with
monitor/keyboard.

## 2. Clean The Dog And Copy Fresh Files

Run these commands from your Mac terminal, not inside the SSH session:

```bash
ssh firefly@192.168.234.1 'rm -rf ~/Aegies-Height && mkdir -p ~/Aegies-Height'

cd "/Users/agentech/Documents/Aegies-Height"

rsync -av --delete \
  --exclude '.git/' \
  --exclude 'camera_calibration_runs/' \
  ./ firefly@192.168.234.1:~/Aegies-Height/
```

This leaves the dog clean. It copies the code, `test_camera.jpg`, and the
annotated reference image at:

```text
~/Aegies-Height/docs/images/l_shape_grid_box_labels.jpg
```

The Agentech library and FF SDK devkit are now a separate sibling project. If
the robot needs SDK wheels or vendor examples, copy or clone that project beside
this one so these paths exist:

```text
~/Aegies-Height
~/agentech_sdk
```

Then SSH in:

```bash
ssh firefly@192.168.234.1
cd ~/Aegies-Height
```

Check that the only calibration starting image/reference files are present:

```bash
ls test_camera.jpg docs/images/l_shape_grid_box_labels.jpg
ls camera_calibration_runs
```

The last command should say `No such file or directory` before you start a new
calibration. That is good: it means no old calibration run is left.

If the dog has GitHub access later, this also works:

```bash
git clone git@github.com:wesleyfan2015/Aegies-Height.git
cd Aegies-Height
```

If Ethernet gives the dog a different IP, replace `192.168.234.1` with that IP.

To delete only old calibration images later, run this on the dog:

```bash
rm -rf ~/Aegies-Height/camera_calibration_runs
```

## 3. Install Dependencies

On the dog:

```bash
python3 -m pip install -r requirements-vision.txt
```

If you need the SDK wheel on the robot:

```bash
python3 -m pip install --no-index --find-links ../agentech_sdk/agentech_sdk/wheels ff_sdk==0.1.0a2
```

If testing from a Linux laptop connected to the dog:

```bash
python3 -m pip install --no-index --find-links ../agentech_sdk/agentech_sdk/wheels ff_sdk==0.1.0a2
```

## 4. Quick Software Checks

Check YOLO:

```bash
python3 examples/vision/height_calculator.py verify-yolo
```

Expected:

```text
yolo_loaded=true
```

Check the Raspberry Pi HC-SR04 depth sensor. The project defaults are trigger
GPIO 17 and echo GPIO 27:

```bash
python3 examples/vision/read_depth_sensor.py
```

One JSON sample:

```bash
python3 examples/vision/read_depth_sensor.py --once --json
```

The height calculator uses those same pins:

```bash
python3 examples/vision/height_calculator.py read-distance
```

Reminder: the HC-SR04 echo pin is 5V. Use a voltage divider or level shifter so
the Pi GPIO input only receives 3.3V.

Check robot posture and walking separately.

The vendor docs point to the SDK walking demo:

```bash
cd ~/Aegies-Height
FF_SDK_D1_VARIANT=zsl-1 FF_SDK_D1_HOST=192.168.234.1 python3 ../agentech_sdk/agentech_sdk/examples/d1/udp_walk.py
```

The project-specific movement scripts from the earlier working path are:

```bash
cd ~/Aegies-Height
python3 ../agentech_sdk/examples/d1/raw_zsibot_sequence.py --host 192.168.234.1 --variant zsl-1
python3 ../agentech_sdk/examples/d1/raw_zsibot_move.py forward --host 192.168.234.1 --variant zsl-1 --skip-stand --pre-move-delay 1.0
python3 ../agentech_sdk/examples/d1/raw_zsibot_move.py back --host 192.168.234.1 --variant zsl-1
python3 ../agentech_sdk/examples/d1/raw_zsibot_move.py yaw_left --host 192.168.234.1 --variant zsl-1
python3 ../agentech_sdk/examples/d1/raw_zsibot_move.py zero --host 192.168.234.1 --variant zsl-1
```

For move-forward-only tests, first get the robot standing and stable, then send
only the forward command:

```bash
python3 ../agentech_sdk/examples/d1/raw_zsibot_move.py zero --host 192.168.234.1 --variant zsl-1 --stand-wait 5.0 --seconds 1.0
python3 ../agentech_sdk/examples/d1/raw_zsibot_move.py forward --host 192.168.234.1 --variant zsl-1 --skip-stand --pre-move-delay 1.0 --warmup-seconds 1.5 --seconds 1.0 --stop-seconds 1.0
```

If the movement scripts connect but print:

```text
Cannot transition to 'move' state: must transition to 'standUp' first.
```

then the backend does not believe the robot is in stand-up mode yet. Try the
full sequence script first because it calls `motion.stand()`, warms up zero
velocity, then streams movement through the same SDK backend.

For posture-only sanity check:

```bash
cd ~/Aegies-Height
python3 ../agentech_sdk/agentech_sdk/examples/motion/stand_damping.py --target D1-DEMO
```

Check calibration script commands:

```bash
python3 examples/vision/grid_laser_calibration.py --help
```

Expected commands:

```text
inspect-grid
capture-grid
capture-laser-samples
calibrate
calibrate-laser
```

## 5. Next Demo: Same-Height Pitch/Level Test

This is the next path to run.

1. Measure the dog camera lens height from the floor.
2. Put tape/mark on the wall at exactly the same height.
3. Put another mark a known distance above or below it, for example 30 cm or 60 cm.
4. Measure the distance from the dog camera lens to the wall.
5. Take one lights-on photo from the dog camera.
6. Use the pixel row of the same-height mark to solve the level/pitch reference.
7. Use the known vertical span to verify the FOV/angle math.

The old laser/grid work is useful here because it gives a starting vertical FOV:

```text
vertical_fov_deg ~= 32.5
```

If this test does not match the known 30 cm or 60 cm wall span, the likely causes
are distance measurement, camera pitch offset, or FOV estimate.

## 6. Reference: Wall Grid + Laser Calibration

This path was used to estimate camera FOV and distortion. Do not keep collecting
laser samples unless we decide to redo lens calibration with a better target.

The grid and laser calibration does **not** train AI. It solves camera geometry:

```text
real grid position in centimeters <-> camera pixel position
```

The output is:

```text
camera_calibration_runs/latest/calibration.json
```

That file contains camera intrinsics and distortion coefficients. Later, the
tilt/height math can use this to be more accurate.

Current measured estimate from the saved calibration set:

```text
horizontal_fov_deg ~= 53.5
vertical_fov_deg   ~= 32.5
```

Treat these as starting estimates until verified with a known wall measurement.

### 6.1 Confirm Grid Measurements

Before running commands, confirm:

```text
grid_rows       = number of horizontal grid lines/intersections
grid_cols       = number of vertical grid lines/intersections
square_size_cm  = real measured square size
```

Current default:

```text
grid_shape = l_shape
total grid lines = 13 horizontal x 8 vertical
lower grid intersections = 9 rows x 8 cols
lower grid boxes = 8 rows x 7 cols
top extension boxes = 4 rows x 2 cols
square_size_cm = 15
roi = 700,420,320,390 for test_camera.jpg
```

Use `docs/images/l_shape_grid_box_labels.jpg` as the reference image. Lower
boxes are labeled `1,1` through `8,7`. Top-extension boxes are labeled `T1,1`
through `T4,2`.

### 6.2 Inspect The Existing Test Image

Run:

```bash
python3 examples/vision/grid_laser_calibration.py inspect-grid \
  --image test_camera.jpg \
  --roi 700,420,320,390 \
  --min-line-length 25
```

Good result:

```text
grid_found=true
point_count=84
```

Why `84`:

```text
72 lower-grid intersections + 12 top-extension intersections = 84
```

If `grid_found=false`, check:

- the grid line color is visible
- the image is not too dark
- the grid row/column counts are correct
- `--blue-hue-low` / `--blue-hue-high` may need adjustment
- `--min-line-length` may need adjustment

### 6.3 Capture Grid Images From The Dog Camera

Run this while the dog camera sees the wall grid:

```bash
python3 examples/vision/grid_laser_calibration.py capture-grid \
  --count 200 \
  --interval-sec 0.1 \
  --roi 700,420,320,390 \
  --min-line-length 25
```

Move the dog/camera or grid view enough that the grid appears in different parts
of the image. Variety matters more than thousands of identical images.

Saved images:

```text
camera_calibration_runs/latest/images/
```

Capture report:

```text
camera_calibration_runs/latest/images/capture_records.json
```

Good result:

```text
accepted_count should be at least 30
```

### 6.4 Calibrate From Grid Images

Run:

```bash
python3 examples/vision/grid_laser_calibration.py calibrate \
  --image-dir camera_calibration_runs/latest/images \
  --output camera_calibration_runs/latest/calibration.json \
  --min-accepted 30 \
  --roi 700,420,320,390 \
  --min-line-length 25
```

Good result:

```text
calibration_saved=camera_calibration_runs/latest/calibration.json
accepted_count >= 30
rms_reprojection_error is low
```

Lower RMS is better. If RMS is high, capture better grid images.

### 6.5 Recommended: Dark-Room Laser Samples With Lights-On Grid Reference

Use this when the green laser is easier to see in darkness.

Do not move the dog or wall grid between the lights-on and lights-off steps.

First, keep the lights on and capture the grid reference:

```bash
python3 examples/vision/grid_laser_calibration.py capture-grid-reference \
  --output camera_calibration_runs/latest/grid_reference.json \
  --image-output camera_calibration_runs/latest/grid_reference.jpg \
  --min-line-length 25
```

Good result:

```text
grid_reference_saved=...
grid_found=true point_count=84
```

If the command hangs while reading the camera, use an already captured image:

```bash
python3 examples/vision/grid_laser_calibration.py capture-grid-reference \
  --image test_camera.jpg \
  --output camera_calibration_runs/latest/grid_reference.json \
  --image-output camera_calibration_runs/latest/grid_reference.jpg \
  --min-line-length 25
```

Then turn the lights off, point the green laser into a box, and start dark
laser capture:

```bash
python3 examples/vision/grid_laser_calibration.py capture-laser-samples \
  --interactive \
  --count 50 \
  --grid-reference camera_calibration_runs/latest/grid_reference.json \
  --roi 650,380,450,460 \
  --box-margin-px 20 \
  --burst-frames 5 \
  --burst-interval-sec 0.05 \
  --grid-retry-frames 1 \
  --laser-min-area 1 \
  --laser-min-saturation 6 \
  --laser-min-value 10
```

When prompted, type the box where the laser is:

```text
1,1
3,5
T1,1
```

In this mode the dark image does not need to show the grid. The script uses the
saved lights-on grid reference and only detects the green laser.

### 6.6 Fallback: Capture Laser-Labeled Samples With Grid Visible

This is the assisted calibration step.

Point the laser into a grid box, then tell the script which box it is in.
OpenCV detects the laser dot and checks whether it is inside the box label you
typed.

Lower boxes are counted from the top-left starting at:

```text
row 1, col 1
```

The lower rectangle has:

```text
7 box rows
7 box columns
```

The top extension uses labels `Trow,col`:

```text
T1,1 is the upper-left top-extension box
T4,2 is the lower-right top-extension box
```

Run:

```bash
python3 examples/vision/grid_laser_calibration.py capture-laser-samples \
  --interactive \
  --count 50 \
  --roi 700,420,320,390 \
  --min-line-length 25
```

If the live camera says `laser_detected=true grid_found=false`, the dog may
still see the grid. It usually means the ROI crop is wrong for the live camera
position. Stop the command, clean the bad partial run, and use a larger ROI:

```bash
rm -rf camera_calibration_runs

python3 examples/vision/grid_laser_calibration.py capture-laser-samples \
  --interactive \
  --count 50 \
  --roi 650,380,450,460 \
  --min-line-length 25
```

If that still cannot find the grid, test without an ROI:

```bash
rm -rf camera_calibration_runs

python3 examples/vision/grid_laser_calibration.py capture-laser-samples \
  --interactive \
  --count 50 \
  --min-line-length 25
```

The script only saves accepted samples by default. Rejected attempts are not
added to `laser_samples.jsonl`.

When prompted:

```text
sample 1/50 box row,col (or q)>
```

Type values like:

```text
3,5
T1,1
```

Saved laser images:

```text
camera_calibration_runs/latest/laser_images/
```

Saved labels:

```text
camera_calibration_runs/latest/laser_samples.jsonl
```

Good result for each sample:

```text
laser_detected=true
grid_found=true
box_check=inside
```

If `box_check=outside`, the laser dot is not inside the box you typed. Move the
laser or type the correct label on the next sample. The final calibration
rejects outside samples.

If the laser is not detected:

- try a darker room
- use the green laser; green is now the default in the scripts
- adjust `--laser-min-area`
- lower `--laser-min-saturation`
- lower `--laser-min-value`
- adjust `--laser-max-area`

### 6.7 Calibrate With Laser Samples

Run:

```bash
python3 examples/vision/grid_laser_calibration.py calibrate-laser \
  --samples camera_calibration_runs/latest/laser_samples.jsonl \
  --output camera_calibration_runs/latest/calibration.json \
  --min-accepted 10 \
  --grid-reference camera_calibration_runs/latest/grid_reference.json \
  --roi 650,380,450,460 \
  --min-line-length 25
```

Good result:

```text
calibration_saved=camera_calibration_runs/latest/calibration.json
accepted_count >= 10
rms_reprojection_error is low
laser_error_px_avg is low
```

Keep the generated file:

```text
camera_calibration_runs/latest/calibration.json
```

## 7. How To Check If Calibration Is Correct

Check the calibration JSON:

```bash
python3 -m json.tool camera_calibration_runs/latest/calibration.json | head -80
```

Look for:

```text
camera_matrix
distortion_coefficients
rms_reprojection_error
accepted_count
rejected_count
```

Good signs:

- `accepted_count` is high
- `rejected_count` is low
- `rms_reprojection_error` is low
- laser samples show low average pixel error
- accepted images are from varied positions/angles

Bad signs:

- most images are rejected
- the wrong grid row/column count was used
- the grid was not flat
- square size was measured wrong
- the laser dot was labeled with the wrong box number
- the laser reflected or bloomed too much

## 8. Tilt Path For Later

Do this later, after or separate from calibration.

Tilt testing answers:

- does Python expose D1 `motion.attitude_control()`?
- does Python expose `state.pose()` body pitch?
- does pitch telemetry change after a small pitch command?
- does the camera image change when the dog tilts?

Safe no-tilt probe:

```bash
python3 examples/vision/tilt_telemetry_probe.py \
  --host 192.168.234.1 \
  --stand \
  --skip-tilt
```

Tiny tilt probe:

```bash
python3 examples/vision/tilt_telemetry_probe.py \
  --host 192.168.234.1 \
  --stand \
  --pitch-vel -0.04 \
  --pitch-seconds 0.5
```

Opposite direction:

```bash
python3 examples/vision/tilt_telemetry_probe.py \
  --host 192.168.234.1 \
  --stand \
  --pitch-vel 0.04 \
  --pitch-seconds 0.5
```

Look for:

```text
connected: true
available_motion_methods includes "attitude_control"
initial_pose
after_tilt_pose
before_image.detections
after_image.detections
```

Saved images:

```text
tilt_probe_runs/latest/
```

## 8.5 Auto-Aim Height Loop

Run this on the Raspberry Pi, because the Pi owns the GPIO depth sensor. The Pi
captures the robot camera stream, reads depth, decides how the robot should
move, and can optionally send small robot commands.

First run dry, with no robot motion:

```bash
python3 examples/vision/auto_aim_height.py \
  --host 192.168.234.1 \
  --max-steps 3
```

If the decisions look correct, allow small forward/back/yaw movement:

```bash
python3 examples/vision/auto_aim_height.py \
  --host 192.168.234.1 \
  --stand-first \
  --enable-motion \
  --max-steps 5 \
  --target-distance-cm 150
```

Pitch is separate and should only be enabled after confirming pitch direction
with `tilt_telemetry_probe.py`:

```bash
python3 examples/vision/auto_aim_height.py \
  --host 192.168.234.1 \
  --stand-first \
  --enable-motion \
  --enable-pitch \
  --pitch-speed 0.04 \
  --max-steps 5
```

Safety defaults are intentionally small:

```text
forward/back speed: 0.08 m/s
yaw speed: 0.12 rad/s
pitch speed: 0.04 rad/s
command duration: 0.45 s
```

## 9. Questions For The Dog Developers

Answered developer notes:

```text
1. D1 `motion.attitude_control(roll_vel, pitch_vel, yaw_vel, height_vel)` is quadruped-only.
2. roll_vel / pitch_vel / yaw_vel are rad/s, range about -0.5..0.5.
3. height_vel is m/s, range about -0.5..0.5.
4. These are physical units, not normalized values.
5. Negative pitch_vel means the head/camera pitches downward in the current D1 joystick mapping.
6. For first tests, keep pitch_vel around +/-0.10..0.15 rad/s and use short duration.
7. `state.pose()` returns body pose including roll/pitch/yaw in radians when supported.
8. pose pitch is the robot current body/IMU fused Euler pose, not camera-only pitch.
9. The camera has a fixed mounting angle relative to the body.
10. The fixed camera mount offset cannot be read from the model; measure it on the real robot.
11. The camera is fixed on the body and follows body pitch.
12. There is no known direct camera pitch API.
13. Camera center height from the floor must be measured on the real robot.
14. If the robot only has dog_task UDP fallback, pitch/yaw are continuous but roll/height are discrete direction pulses.
```

Height math implication:

```text
camera_pitch = body_pitch_from_state_pose + measured_camera_mount_offset
```

Use this only after the same-height wall mark has established the real level
row. For the next demo, the wall-mark level calibration is still the main path.

## 10. What To Send Back After Today

Send:

- terminal output from `inspect-grid`
- terminal output from `capture-grid`
- terminal output from `calibrate`
- terminal output from `capture-laser-samples`
- terminal output from `calibrate-laser`
- `camera_calibration_runs/latest/calibration.json`
- a few accepted grid images
- a few laser images
- notes on grid square size and grid row/column count

That gives enough information to verify whether the camera calibration is good.
