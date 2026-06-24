param(
    [string]$Robot = "aegies-robot",
    [int]$ExpectedCount = 64
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
$LocalOutput = Join-Path $RepoRoot "camera_calibration_runs\accepted_laser_64"

$remotePython = @"
import json
import shutil
import sys
from pathlib import Path

expected_count = $ExpectedCount
home = Path("/home/firefly")

preferred = home / "Aegies-Height" / "camera_calibration_runs" / "latest" / "laser_samples.jsonl"
candidates = []
if preferred.exists():
    candidates.append(preferred)

for path in home.rglob("laser_samples.jsonl"):
    if path not in candidates and "camera_calibration_runs" in path.parts:
        candidates.append(path)

if not candidates:
    print("ERROR=no_laser_samples_jsonl_found")
    sys.exit(2)

def priority(path):
    text = str(path)
    if "/Aegies-Height/camera_calibration_runs/" in text:
        return 0
    if "Aegies-Height_KEEP" in text:
        return 1
    if "Aegies-Height_OLD" in text:
        return 2
    return 3

samples_path = sorted(candidates, key=priority)[0]
root = samples_path.parent
keep_dir = root / "accepted_laser_images"
clean_jsonl = root / "laser_samples_accepted_only.jsonl"

if keep_dir.exists():
    shutil.rmtree(keep_dir)
keep_dir.mkdir(parents=True, exist_ok=True)

accepted = []
missing = []
for line in samples_path.read_text().splitlines():
    if not line.strip():
        continue
    row = json.loads(line)
    if not row.get("sample_accepted"):
        continue

    image_value = row.get("image") or row.get("image_path")
    if not image_value:
        missing.append("<missing image key>")
        continue

    image = Path(image_value)
    search_paths = []
    if image.is_absolute():
        search_paths.append(image)
    else:
        search_paths.extend([
            Path.cwd() / image,
            root / image,
            root / "laser_images" / image.name,
        ])

    source = next((candidate for candidate in search_paths if candidate.exists()), None)
    if source is None:
        missing.append(str(image_value))
        continue

    dst = keep_dir / source.name
    shutil.copy2(source, dst)
    row["image"] = str(dst)
    accepted.append(row)

with clean_jsonl.open("w") as f:
    for row in accepted:
        f.write(json.dumps(row) + "\n")

print(f"samples_path={samples_path}")
print(f"run_root={root}")
print(f"accepted_images_copied={len(accepted)}")
print(f"missing_accepted_images={len(missing)}")
print(f"keep_dir={keep_dir}")
print(f"clean_jsonl={clean_jsonl}")

if missing:
    print("MISSING_FIRST_20_START")
    for item in missing[:20]:
        print(item)
    print("MISSING_FIRST_20_END")

if len(accepted) != expected_count:
    print(f"ERROR=expected_{expected_count}_accepted_images_but_copied_{len(accepted)}")
    sys.exit(3)

for junk in [
    root / "laser_images",
    root / "debug_attempts",
    root / "latest_laser_attempt.jpg",
    root / "latest_laser_debug.jpg",
]:
    if junk.is_dir():
        shutil.rmtree(junk)
        print(f"deleted_dir={junk}")
    elif junk.exists():
        junk.unlink()
        print(f"deleted_file={junk}")

print("cleanup_status=ok")
"@

Write-Host "Connecting to $Robot and creating accepted image set..."
$remoteOutput = $remotePython | ssh $Robot "python3 -"
$remoteOutput | ForEach-Object { Write-Host $_ }

$acceptedLine = $remoteOutput | Where-Object { $_ -like "accepted_images_copied=*" } | Select-Object -First 1
if (-not $acceptedLine) {
    throw "Robot did not report accepted_images_copied."
}
$acceptedCount = [int]($acceptedLine -replace "^accepted_images_copied=", "").Trim()
if ($acceptedCount -ne $ExpectedCount) {
    throw "Expected $ExpectedCount accepted images, but robot copied $acceptedCount. Nothing was downloaded."
}

$keepDir = (($remoteOutput | Where-Object { $_ -like "keep_dir=*" } | Select-Object -First 1) -replace "^keep_dir=", "").Trim()
$cleanJsonl = (($remoteOutput | Where-Object { $_ -like "clean_jsonl=*" } | Select-Object -First 1) -replace "^clean_jsonl=", "").Trim()
$runRoot = (($remoteOutput | Where-Object { $_ -like "run_root=*" } | Select-Object -First 1) -replace "^run_root=", "").Trim()

if (-not $keepDir -or -not $cleanJsonl -or -not $runRoot) {
    throw "Could not parse robot output paths."
}

if (Test-Path $LocalOutput) {
    Remove-Item -LiteralPath $LocalOutput -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $LocalOutput | Out-Null

Write-Host "Downloading accepted images into $LocalOutput ..."
scp -r "${Robot}:$keepDir" "$LocalOutput\"
scp "${Robot}:$cleanJsonl" "$LocalOutput\"

$optionalFiles = @("grid_reference.json", "camera_calibration.json", "calibration.json")
foreach ($file in $optionalFiles) {
    ssh $Robot "test -f '$runRoot/$file'"
    if ($LASTEXITCODE -eq 0) {
        scp "${Robot}:$runRoot/$file" "$LocalOutput\"
    }
}

$localImagesDir = Join-Path $LocalOutput "accepted_laser_images"
$localCount = (Get-ChildItem -LiteralPath $localImagesDir -File -Filter "*.jpg" | Measure-Object).Count
Write-Host "local_output=$LocalOutput"
Write-Host "local_accepted_images=$localCount"

if ($localCount -ne $ExpectedCount) {
    throw "Downloaded $localCount images locally, expected $ExpectedCount."
}

Write-Host "Done. Accepted laser images are in:"
Write-Host $localImagesDir
