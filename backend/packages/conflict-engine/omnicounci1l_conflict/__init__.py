"""omnicounci1l-conflict — conflict analysis engine for OmniCouncil."""

from .engine import ConflictEngine
from .result import ConflictPoint, ConflictPosition, ConflictResult

__version__ = "1.0.0"
__all__ = [
    "ConflictEngine",
    "ConflictPoint",
    "ConflictPosition",
    "ConflictResult",
]
