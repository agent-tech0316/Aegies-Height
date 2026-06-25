"""Small Python wrapper for Aegis quadruped control."""

from .config import (
    DEFAULT_SLOW_FORWARD_SPEED_MPS,
    SAFE_MAX_FORWARD_SPEED_MPS,
    THEORETICAL_MAX_FORWARD_SPEED_MPS,
)
from .dog import AsyncDog, Dog
from .exceptions import AgentechError, ConfigurationError, SafetyError
from .models import ActionResult

__all__ = [
    "ActionResult",
    "AgentechError",
    "AsyncDog",
    "ConfigurationError",
    "DEFAULT_SLOW_FORWARD_SPEED_MPS",
    "Dog",
    "SAFE_MAX_FORWARD_SPEED_MPS",
    "SafetyError",
    "THEORETICAL_MAX_FORWARD_SPEED_MPS",
]

__version__ = "0.1.0"
