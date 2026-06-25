from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ActionResult:
    status: str
    action: str
    result: dict[str, Any]
    trace_id: str | None = None
