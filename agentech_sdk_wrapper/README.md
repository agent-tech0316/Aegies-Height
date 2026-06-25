# Agentech SDK Wrapper

This folder wraps the existing Aegis `ff_sdk` robot-control API behind a small
Python package:

```python
import agentech as agt

d = agt.Dog()
d.agt.stand()
d.agt.set_forward_speed(0.3)
d.agt.move_forward(1, unit="s")
d.agt.turn_left(90)
d.agt.stop()
d.close()
```

## Import

From this folder:

```powershell
python -m pip install -e .
python -c "import agentech as agt; print(agt.Dog().mode)"
```

Or without installing:

```powershell
$env:PYTHONPATH="C:\Users\xinga\OneDrive\Documents\GitHub\Aegies-Height\agentech_sdk_wrapper"
python examples\dry_run_demo.py
```

## Modes

- `dry_run`: no hardware access, no real movement. This is the default when no
  `key` is provided.
- `simulation`: local simulation state, no real movement. Useful on Windows.
- `hardware`: connects through `ff_sdk`; requires a `key` or target, Linux or a
  supported robot environment, `ff_sdk` installed, and explicit hardware allow.

Hardware is intentionally opt-in:

```powershell
$env:AGENTECH_ALLOW_HARDWARE="1"
$env:AGENTECH_TARGET="D1-DEMO"
python examples\simple_dog.py --mode hardware --key encrypted_key
```

For early testing, the injected `key` is kept as metadata. In hardware mode this
wrapper uses `target`, `AGENTECH_TARGET`, or finally `key` as the `ff_sdk.connect`
target placeholder until the backend key-to-robot mapping is finalized.

## Tests

```powershell
python -m unittest discover -s tests
```

See `docs/agentech_sdk_functions.md` for the function-by-function contract.
