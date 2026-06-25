"""Student-friendly Agentech robot dog controls.

Typical use:

    from agentech import Agentech

    Agentech.forward(speed=0.3, seconds=1.0)
    Agentech.turn_left(angle=45)
    Agentech.stop()
"""

from .aegis import Agentech, Robot

__all__ = ["Agentech", "Robot"]
