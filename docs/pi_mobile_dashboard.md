# Pi Mobile Dashboard

Run this on the Raspberry Pi so a phone or laptop on the same network can start/stop the height tools and view the latest annotated images.

## Start

```bash
cd ~/Aegies-Height
python3 scripts/pi_height_dashboard.py --host 0.0.0.0 --port 8000
```

Open this from a browser:

```text
http://<pi-ip>:8000
```

Find the Pi IP:

```bash
hostname -I
ip -4 addr show wlan0
ip -4 addr show eth0
```

Use the IP for the network your phone is also connected to.

## Background Mode

```bash
cd ~/Aegies-Height
mkdir -p dashboard_logs
nohup python3 scripts/pi_height_dashboard.py --host 0.0.0.0 --port 8000 > dashboard_logs/pi_height_dashboard.log 2>&1 &
```

Stop it:

```bash
pkill -f pi_height_dashboard.py
```

## Buttons

- `Start Watch Only`: detect person/depth and save annotated frames, no robot tilt.
- `Start Height Auto Tilt`: run the height pipeline with automatic tilt.
- `Run One Frame`: capture one annotated frame.
- `Wait For RT Tilt`: wait for the RT trigger, then run the standing-only RT tilt sequence.
- `Stop All`: stop programs started by this dashboard.

The dashboard itself does not put the robot into damping mode.
