# Aegies Height

Aegies Height is the height-measurement workspace for the Aegis/D1 robot dog.
This repo now focuses on camera calibration, depth sensing, live person-height
capture, robot test runbooks, and project-specific movement probes.

The Agentech Python library and official FF SDK devkit have been moved into a
separate sibling project:

```text
../agentech_sdk/
```

Use that project for `agentech`, the bundled `ff_sdk 0.1.0a2` wheels, the FF SDK
docs/examples, C++ SDK files, and Agentech wrapper tests.

## Layout

```text
examples/vision/       # Height, camera, depth, pitch, and auto-aim workflows
scripts/               # Height dashboards, robot helpers, calibration utilities
docs/                  # Height workflow docs and robot runbooks
calibrations/          # Checked-in calibration references
calibration_targets/   # Printable calibration targets
models/                # Vision models
```

## SDK Dependency

Install the robot SDK from the sibling Agentech SDK project:

```bash
python -m pip install --no-index --find-links ../agentech_sdk/agentech_sdk/wheels ff_sdk==0.1.0a2
```

For Agentech one-line commands or the MuJoCo simulator, work from:

```bash
cd ../agentech_sdk
python -m pip install -e .
```

## Height Workflow

Start with the robot runbook:

```text
docs/dog_testing_runbook.md
```

The main height and camera scripts are under `examples/vision/`, especially
`height_calculator.py`, `human_height_live.py`, `grid_laser_calibration.py`, and
`tilt_telemetry_probe.py`.
