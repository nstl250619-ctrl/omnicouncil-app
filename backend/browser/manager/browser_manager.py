"""Browser lifecycle manager."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class BrowserManager:
    """Manages browser lifecycle (launch, connect, disconnect)."""

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected and self._browser is not None

    async def launch(self, headless: bool = True) -> bool:
        """Launch a new browser instance."""
        try:
            from patchright.async_api import async_playwright
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            self._connected = True
            logger.info("Browser launched (headless=%s)", headless)
            return True
        except Exception as e:
            logger.error("Failed to launch browser: %s", e)
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Close browser and cleanup."""
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None
        self._connected = False
        logger.info("Browser disconnected")

    @property
    def playwright(self):
        return self._playwright

    @property
    def browser(self):
        return self._browser
