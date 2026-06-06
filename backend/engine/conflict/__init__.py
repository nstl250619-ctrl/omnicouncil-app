"""Conflict engine — analyzes why AIs disagree."""
from .engine import ConflictEngine
from .result import ConflictPoint, ConflictPosition, ConflictResult

__all__ = ["ConflictEngine", "ConflictPoint", "ConflictPosition", "ConflictResult"]
