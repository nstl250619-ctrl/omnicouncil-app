"""Page Interaction Manager — config-driven page interaction.

All platform-specific knowledge (selectors, UI elements, login patterns)
comes from PageInteractionConfig. No hardcoded selectors in adapters.

Usage:
    manager = PageInteractionManager(config.page)
    input_el = await manager.find_input(page)
    response = await manager.extract_response(page, prompt, timeout_ms)
    ok, reason = await manager.pre_flight_check(page)
"""

from __future__ import annotations

import logging
import time
from typing import Any

from engine.contracts import PageInteractionConfig

logger = logging.getLogger(__name__)


class InputFinder:
    """Config-driven input element discovery."""

    def __init__(self, selectors: list[str]) -> None:
        self._selectors = selectors

    async def find(self, page: Any) -> Any:
        """Return first visible input element from selector list."""
        for sel in self._selectors:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=2000):
                    return el
            except Exception:
                continue
        return None


class ResponseExtractor:
    """Config-driven response extraction."""

    def __init__(
        self,
        response_selectors: list[str],
        ui_elements: list[str],
        stop_button_selectors: list[str],
    ) -> None:
        self._response_selectors = response_selectors
        self._ui_elements = set(ui_elements)
        self._stop_button_selectors = stop_button_selectors

    async def extract(self, page: Any, prompt: str, timeout_ms: int) -> str:
        """Extract response with idle detection loop."""
        idle_ms = 3000
        last_response = ""
        idle_start = None
        deadline = time.time() + timeout_ms / 1000

        while time.time() < deadline:
            # Check stop button
            stop_btn = await self._find_stop_button(page)
            if stop_btn is not None:
                try:
                    if await stop_btn.is_visible(timeout=500):
                        idle_start = None
                        await page.wait_for_timeout(500)
                        continue
                except Exception:
                    pass

            # Try selector extraction
            response_text = await self._try_selector_extraction(page, prompt)

            if response_text:
                if response_text != last_response:
                    last_response = response_text
                    idle_start = time.time()
                elif idle_start and (time.time() - idle_start) * 1000 >= idle_ms:
                    return response_text

            await page.wait_for_timeout(500)

        if last_response:
            return last_response
        raise TimeoutError("Response extraction timed out")

    async def _try_selector_extraction(self, page: Any, prompt: str) -> str:
        """Extract response using configured CSS selectors."""
        for sel in self._response_selectors:
            try:
                elements = page.locator(sel)
                count = await elements.count()
                if count > 0:
                    text = await elements.nth(count - 1).inner_text(timeout=2000)
                    text = text.replace("\xa0", " ").strip()
                    if text and len(text) > 2 and prompt not in text:
                        clean = "\n".join(
                            ln for ln in text.split("\n")
                            if not self._is_ui_element(ln.strip())
                        )
                        if clean:
                            return clean
            except Exception:
                continue
        return ""

    async def _find_stop_button(self, page: Any) -> Any:
        """Find stop button using configured selectors."""
        for sel in self._stop_button_selectors:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=500):
                    return el
            except Exception:
                continue
        return None

    def _is_ui_element(self, text: str) -> bool:
        """Check if text is a UI element to filter out."""
        return text in self._ui_elements or len(text) < 2


class PreFlightChecker:
    """Config-driven pre-flight check."""

    def __init__(
        self,
        login_url_patterns: list[str],
        cloudflare_check: bool,
        input_selectors: list[str],
    ) -> None:
        self._login_patterns = login_url_patterns
        self._cloudflare_check = cloudflare_check
        self._input_selectors = input_selectors

    async def check(self, page: Any) -> tuple[bool, str]:
        """Run pre-flight checks: URL, Cloudflare, input availability."""
        if page.is_closed():
            return False, "page_closed"

        url = page.url

        # Check login URL patterns
        for pattern in self._login_patterns:
            if pattern in url.lower():
                return False, "login_required"

        # Check Cloudflare challenge
        if self._cloudflare_check:
            try:
                title = await page.title()
                if "just a moment" in title.lower() or "cloudflare" in title.lower():
                    return False, "cloudflare_challenge"
            except Exception:
                return False, "page_unresponsive"

        # Check input element exists
        try:
            for sel in self._input_selectors:
                try:
                    el = page.locator(sel).first
                    if await el.is_visible(timeout=2000):
                        return True, "ok"
                except Exception:
                    continue
            return False, "input_missing"
        except Exception:
            return False, "input_check_failed"


class PageInteractionManager:
    """Unified page interaction manager.

    Creates InputFinder, ResponseExtractor, PreFlightChecker from config.
    Provider adapters call manager.find_input(page) etc.
    """

    def __init__(self, config: PageInteractionConfig | None) -> None:
        if config is None:
            # Fallback defaults
            config = PageInteractionConfig(
                input_selectors=["textarea", "[contenteditable='true']", "[role='textbox']"],
                response_selectors=["[data-role='assistant']", "[class*='response']"],
                stop_button_selectors=["button[aria-label='Stop generating']"],
                ui_elements=[],
                login_url_patterns=["login", "signin", "sign-in"],
                cloudflare_check=True,
            )

        self.input_finder = InputFinder(config.input_selectors)
        self.response_extractor = ResponseExtractor(
            response_selectors=config.response_selectors,
            ui_elements=config.ui_elements,
            stop_button_selectors=config.stop_button_selectors,
        )
        self.pre_flight_checker = PreFlightChecker(
            login_url_patterns=config.login_url_patterns,
            cloudflare_check=config.cloudflare_check,
            input_selectors=config.input_selectors,
        )

    async def find_input(self, page: Any) -> Any:
        """Find input element on page."""
        return await self.input_finder.find(page)

    async def extract_response(self, page: Any, prompt: str, timeout_ms: int) -> str:
        """Extract AI response from page."""
        return await self.response_extractor.extract(page, prompt, timeout_ms)

    async def pre_flight_check(self, page: Any) -> tuple[bool, str]:
        """Run pre-flight checks."""
        return await self.pre_flight_checker.check(page)
