"""Centralized logging configuration for OmniCouncil backend.

Usage:
    from shared.logger import get_logger
    logger = get_logger(__name__)
    logger.info("something happened")
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

_CONFIGURED = False


def _ensure_configured() -> None:
    """Configure root logger once (idempotent)."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    root = logging.getLogger("omnicouncil")
    root.setLevel(logging.DEBUG)

    # Console handler — INFO and above
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(
        "[%(asctime)s] %(levelname)-7s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    ))
    root.addHandler(console)

    # File handler — DEBUG and above (cross-platform log path)
    try:
        log_dir = Path.home() / ".omnicouncil"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "omnicouncil.log"
        file_handler = logging.FileHandler(str(log_file), encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(
            "[%(asctime)s] %(levelname)-7s %(name)s:%(lineno)d — %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        root.addHandler(file_handler)
    except Exception:
        # Never let logging setup crash the app
        pass


def get_logger(name: str) -> logging.Logger:
    """Get a logger under the 'omnicouncil' namespace.

    Args:
        name: Module name (typically __name__).

    Returns:
        Configured logger instance.
    """
    _ensure_configured()
    # Strip leading 'backend.' if present for cleaner names
    clean = name.removeprefix("backend.")
    return logging.getLogger(f"omnicouncil.{clean}")
