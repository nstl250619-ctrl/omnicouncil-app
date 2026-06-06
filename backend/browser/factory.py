"""Browser engine factory."""

from __future__ import annotations

import logging
from pathlib import Path

from .cdp_engine import CDPEngine
from .embedded_engine import EmbeddedEngine
from .engine import BrowserEngine, EngineMode

logger = logging.getLogger(__name__)


def create_engine(
    mode: EngineMode | str,
    auth_dir: str | None = None,
    cdp_url: str = "http://localhost:9222",
    headless: bool = True,
) -> BrowserEngine:
    """Create a browser engine based on the specified mode.

    Args:
        mode: Engine mode ('cdp' or 'embedded')
        auth_dir: Directory for storing auth state files
        cdp_url: CDP connection URL (for CDP mode)
        headless: Whether to run headless (for embedded mode)

    Returns:
        BrowserEngine instance
    """
    if isinstance(mode, str):
        mode = EngineMode(mode)

    auth_dir = auth_dir or str(Path.home() / ".omnicouncil" / "auth")

    if mode == EngineMode.CDP:
        logger.info("Creating CDP engine (url=%s)", cdp_url)
        return CDPEngine(cdp_url=cdp_url, auth_dir=auth_dir)
    else:
        logger.info("Creating embedded engine (headless=%s)", headless)
        return EmbeddedEngine(auth_dir=auth_dir, headless=headless)
