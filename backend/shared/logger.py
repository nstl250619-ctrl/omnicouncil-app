"""Centralized logging configuration for OmniCouncil backend.

Usage:
    from shared.logger import get_logger
    logger = get_logger(__name__)
    logger.info("something happened")

Production features:
- Rotating file handler (max 10MB per file, 5 backup files)
- Sensitive data redaction (API keys, tokens)
- Configurable log level via LOG_LEVEL env var or config.yaml
"""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONFIGURED = False

# Fields to redact in log messages
_SENSITIVE_PATTERNS = [
    "api_key",
    "api-key",
    "apikey",
    "token",
    "secret",
    "password",
    "authorization",
    "cookie",
]


def _redact_sensitive(msg: str) -> str:
    """Redact sensitive values from log messages."""
    import re

    result = msg
    for pattern in _SENSITIVE_PATTERNS:
        # Match "key=value" or "key: value" or "key": "value" patterns
        result = re.sub(
            rf'({pattern}["\']?\s*[:=]\s*["\']?)([^"\'\s,}}]+)',
            r'\1[REDACTED]',
            result,
            flags=re.IGNORECASE,
        )
    return result


class RedactingFormatter(logging.Formatter):
    """Formatter that redacts sensitive data from log records."""

    def format(self, record: logging.LogRecord) -> str:
        original = super().format(record)
        return _redact_sensitive(original)


def _ensure_configured() -> None:
    """Configure root logger once (idempotent)."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    # Determine log level from env or default to INFO
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger("omnicouncil")
    root.setLevel(logging.DEBUG)  # Allow all levels, handlers filter

    # Console handler — respects LOG_LEVEL
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(level)
    console.setFormatter(RedactingFormatter(
        "[%(asctime)s] %(levelname)-7s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    ))
    root.addHandler(console)

    # Rotating file handler — DEBUG and above
    try:
        log_dir = Path.home() / ".omnicouncil" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "omnicouncil.log"

        file_handler = RotatingFileHandler(
            str(log_file),
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(RedactingFormatter(
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
