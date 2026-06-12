# Accepted Laser Images Cleanup And Transfer

Use this when you want to delete unusable laser images on the robot and keep only
the accepted calibration set.

The source of truth is:

```text
camera_calibration_runs/latest/laser_samples.jsonl
```

Accepted samples have:

```text
"sample_accepted": true
```

## 1. SSH Into The Robot

From your computer:

```bash
ssh firefly@192.168.234.1
```

Then on the robot:

```bash
cd ~/Aegies-Height
```

## 2. Make A Clean Folder With Only Accepted Images

Run this on the robot:

```bash
python3 - <<'PY'
import json
import shutil
from pathlib import Path

root = Path("camera_calibration_runs/latest")
samples_path = root / "laser_samples.jsonl"
keep_dir = root / "accepted_laser_images"

keep_dir.mkdir(parents=True, exist_ok=True)

accepted = []
for line in samples_path.read_text().splitlines():
    if not line.strip():
        continue
    row = json.loads(line)
    if not row.get("sample_accepted"):
        continue

    image = Path(row["image"])
    if not image.is_absolute():
        image = Path.cwd() / image

    if image.exists():
        dst = keep_dir / image.name
        shutil.copy2(image, dst)
        accepted.append((row, dst.name))

clean_jsonl = root / "laser_samples_accepted_only.jsonl"
with clean_jsonl.open("w") as f:
    for row, name in accepted:
        row["image"] = str(keep_dir / name)
        f.write(json.dumps(row) + "\n")

print("accepted_images_copied=", len(accepted))
print("keep_dir=", keep_dir)
print("clean_jsonl=", clean_jsonl)
PY
```

Expected:

```text
accepted_images_copied= 64
```

## 3. Verify Before Deleting Anything

Run this on the robot:

```bash
find camera_calibration_runs/latest/accepted_laser_images -name '*.jpg' | wc -l
wc -l camera_calibration_runs/latest/laser_samples_accepted_only.jsonl
```

Both should say:

```text
64
```

Do not delete anything until both counts are correct.

## 4. Delete The Unused/Junk Photos On The Robot

Only run this after the accepted image count is correct.

```bash
rm -rf camera_calibration_runs/latest/laser_images
rm -rf camera_calibration_runs/latest/debug_attempts
rm -f camera_calibration_runs/latest/latest_laser_attempt.jpg
rm -f camera_calibration_runs/latest/latest_laser_debug.jpg
```

This keeps:

```text
camera_calibration_runs/latest/accepted_laser_images/
camera_calibration_runs/latest/laser_samples_accepted_only.jsonl
camera_calibration_runs/latest/grid_reference.json
camera_calibration_runs/latest/camera_calibration.json
```

## 5. Copy The Accepted Set From Robot To A Computer

Run this on your computer, not inside SSH:

```bash
mkdir -p ~/Desktop/aegies_accepted_64

rsync -av \
  firefly@192.168.234.1:/home/firefly/Aegies-Height/camera_calibration_runs/latest/accepted_laser_images/ \
  ~/Desktop/aegies_accepted_64/accepted_laser_images/

rsync -av \
  firefly@192.168.234.1:/home/firefly/Aegies-Height/camera_calibration_runs/latest/laser_samples_accepted_only.jsonl \
  ~/Desktop/aegies_accepted_64/

rsync -av \
  firefly@192.168.234.1:/home/firefly/Aegies-Height/camera_calibration_runs/latest/grid_reference.json \
  ~/Desktop/aegies_accepted_64/

rsync -av \
  firefly@192.168.234.1:/home/firefly/Aegies-Height/camera_calibration_runs/latest/camera_calibration.json \
  ~/Desktop/aegies_accepted_64/
```

Then check on your computer:

```bash
find ~/Desktop/aegies_accepted_64/accepted_laser_images -name '*.jpg' | wc -l
ls ~/Desktop/aegies_accepted_64
open ~/Desktop/aegies_accepted_64
```

Expected:

```text
64
```

The folder should contain:

```text
accepted_laser_images/
laser_samples_accepted_only.jsonl
grid_reference.json
camera_calibration.json
```

## 6. Use From Another Computer

On the new computer, connect to the robot network and run the same commands in
section 5. Or copy the finished folder:

```text
~/Desktop/aegies_accepted_64
```

to the new computer.
