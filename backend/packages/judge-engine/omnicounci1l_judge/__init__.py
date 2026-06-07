"""omnicounci1l-judge — AI judge engine for OmniCouncil."""

from .engine import JudgeEngine
from .result import JudgeVerdict

__version__ = "1.0.0"
__all__ = [
    "JudgeEngine",
    "JudgeVerdict",
]
