"""BaseQueryAdapter — abstract base for per-platform query logic.

Replaces the old ``BaseProvider`` which mixed runtime management
(login, browser, session) with query logic (send, wait, extract).

Design rule: ``BaseQueryAdapter`` must NEVER hold a reference to
``BrowserEngine`` or ``AIRuntimeEngine``.  The ``Page`` object is
passed in from the outside by the Scheduler via ``execute()``.

Lifecycle of a single query::

    execute(page, prompt, options)
      → pre_flight_check(page)
      → send_prompt(page, prompt)
      → wait_for_response(page, timeout_ms)
      → extract_result(page)
      → QueryResult
"""

from __future__ import annotations

import logging
import time
from abc import abstractmethod
from dataclasses import dataclass
from typing import Any

from engine.contracts import (
    PageInteractionConfig,
    QueryAdapter as QueryAdapterABC,
)
from engine.contracts import (
    QueryRequest,
    QueryResult,
    QueryState,
    QueryTimeoutError,
    SendError,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QueryAdapterConfig:
    """Configuration for a query adapter."""

    platform: str                       # "deepseek" / "chatgpt" / …
    display_name: str                   # Human-readable name
    home_url: str                       # Chat page URL
    icon_color: str = "#6C5CE7"
    icon_emoji: str = "🤖"


class BaseQueryAdapter(QueryAdapterABC):
    """Base class for all platform query adapters.

    Subclasses must implement:
        - ``config()`` → QueryAdapterConfig

    Optional overrides:
        - ``_find_input(page)`` → element or None (default uses page config)
        - ``_extract_response(page, prompt, timeout_ms)`` → str (default uses page config)
        - ``_is_ui_element(text)`` → bool
        - ``pre_flight_check(page)`` → (ok, reason)
        - ``send_prompt(page, prompt)`` — for custom send logic
        - ``wait_for_response(page, timeout_ms)`` — for custom wait logic

    If ``page_config`` is provided, default implementations of
    ``_find_input`` and ``_extract_response`` will use the configured
    selectors.  Subclasses can still override for platform-specific logic.
    """

    def __init__(self, page_config: PageInteractionConfig | None = None) -> None:
        self._page_config = page_config

    # ── Abstract: configuration ────────────────────────────

    @abstractmethod
    def config(self) -> QueryAdapterConfig:
        """Return this adapter's configuration."""
        ...

    # ── DOM interaction (config-driven defaults) ──────────

    async def _find_input(self, page: Any) -> Any:
        """Locate the input element on the page.

        Default implementation uses ``page_config.input_selectors``.
        Override for platform-specific logic.
        """
        selectors = self._page_config.input_selectors if self._page_config else [
            "textarea", "[contenteditable='true']", "[role='textbox']",
        ]
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=2000):
                    return el
            except Exception:
                continue
        return None

    async def _extract_response(self, page: Any, prompt: str, timeout_ms: int) -> str:
        """Extract the AI's response text from the page.

        Default implementation uses ``page_config.response_selectors``
        with idle detection.  Override for platform-specific logic.
        """
        selectors = self._page_config.response_selectors if self._page_config else [
            "[data-role='assistant']",
            "[class*='response']",
            "[class*='message']",
        ]
        ui_elements = set(self._page_config.ui_elements) if self._page_config else set()

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

            # Try configured selectors
            response_text = ""
            for sel in selectors:
                try:
                    elements = page.locator(sel)
                    count = await elements.count()
                    if count > 0:
                        text = await elements.nth(count - 1).inner_text(timeout=2000)
                        text = text.replace("\xa0", " ").strip()
                        if text and len(text) > 2 and prompt not in text:
                            clean = "\n".join(
                                ln for ln in text.split("\n")
                                if not self._is_ui_element(ln.strip()) and ln.strip() not in ui_elements
                            )
                            if clean:
                                response_text = clean
                                break
                except Exception:
                    continue

            if response_text:
                if response_text != last_response:
                    last_response = response_text
                    idle_start = time.time()
                elif idle_start and (time.time() - idle_start) * 1000 >= idle_ms:
                    return response_text

            await page.wait_for_timeout(500)

        if last_response:
            return last_response
        raise TimeoutError(f"{self.config().display_name} response timed out")

    # ── Public API: execute ────────────────────────────────

    async def execute(
        self,
        page: Any,
        prompt: str,
        options: Any | None = None,
    ) -> QueryResult:
        """Execute a full query: pre-flight → send → wait → extract.

        Args:
            page: A Playwright Page — already navigated, session valid.
            prompt: The user's question.
            options: Optional SubmitOptions (timeout_ms, etc.).

        Returns:
            A ``QueryResult`` with the response or error.
        """
        cfg = self.config()
        timeout_ms = getattr(options, "timeout_ms", 120_000) if options else 120_000
        start = time.time()

        # Pre-flight check
        ok, reason = await self.pre_flight_check(page)
        if not ok:
            return QueryResult(
                request=QueryRequest(platform=cfg.platform, prompt=prompt),
                state=QueryState.FAILED,
                error=f"pre-flight failed: {reason}",
                elapsed_seconds=time.time() - start,
            )

        try:
            # Send prompt
            await self.send_prompt(page, prompt)
            await page.wait_for_timeout(1500)

            # Wait for response to complete
            await self.wait_for_response(page, timeout_ms)

            # Try to get Markdown via copy button first
            markdown = await self._try_copy_markdown(page)
            if markdown:
                response_text = markdown
            else:
                # Fallback: extract HTML from page
                response_text = await self._extract_response(page, prompt, timeout_ms)

            return QueryResult(
                request=QueryRequest(platform=cfg.platform, prompt=prompt),
                state=QueryState.DONE,
                content=response_text,
                elapsed_seconds=time.time() - start,
                attempts=1,
            )

        except (TimeoutError, QueryTimeoutError) as exc:
            return QueryResult(
                request=QueryRequest(platform=cfg.platform, prompt=prompt),
                state=QueryState.TIMEOUT,
                error=str(exc),
                elapsed_seconds=time.time() - start,
                attempts=1,
            )
        except SendError as exc:
            return QueryResult(
                request=QueryRequest(platform=cfg.platform, prompt=prompt),
                state=QueryState.FAILED,
                error=str(exc),
                elapsed_seconds=time.time() - start,
                attempts=1,
            )
        except Exception as exc:
            logger.exception("%s: execute failed", cfg.display_name)
            return QueryResult(
                request=QueryRequest(platform=cfg.platform, prompt=prompt),
                state=QueryState.FAILED,
                error=str(exc),
                elapsed_seconds=time.time() - start,
                attempts=1,
            )

    # ── Default: send_prompt ───────────────────────────────

    async def send_prompt(self, page: Any, prompt: str) -> None:
        """Default send: find input → click → fill → Enter.

        Override for platforms with custom send logic (e.g. ChatGPT's
        send button).
        """
        input_box = await self._find_input(page)
        if input_box is None:
            raise SendError(self.config().platform, "input element not found")

        await input_box.click()
        await page.wait_for_timeout(300)
        await input_box.fill(prompt)
        await page.wait_for_timeout(500)
        await page.keyboard.press("Enter")

    # ── Default: pre_flight_check ──────────────────────────

    async def pre_flight_check(self, page: Any) -> tuple[bool, str]:
        """Quick sanity check before operating on *page*.

        Checks:
            1. Page is not closed.
            2. URL is not a known-bad pattern.
            3. Cloudflare challenge is not blocking.

        Override for platform-specific checks (e.g. DOM-based login
        detection for 千问).
        """
        if page.is_closed():
            return False, "page_closed"

        url = page.url

        # Known-bad URL patterns
        bad_keywords = ["about:blank", "signin", "sign-in", "sign_in", "login", "auth0", "captcha"]
        for kw in bad_keywords:
            if kw in url.lower():
                if kw in ("signin", "sign-in", "sign_in", "login", "auth0"):
                    return False, "login_required"
                return False, f"bad_url:{kw}"

        # Cloudflare challenge
        try:
            title = await page.title()
            if "just a moment" in title.lower() or "cloudflare" in title.lower():
                return False, "cloudflare_challenge"
        except Exception:
            return False, "page_unresponsive"

        # Input element exists
        try:
            input_box = await self._find_input(page)
            if input_box is None:
                return False, "input_missing"
        except Exception:
            return False, "input_check_failed"

        return True, "ok"

    # ── Default: wait_for_response ─────────────────────────

    async def wait_for_response(self, page: Any, timeout_ms: int) -> None:
        """Default wait: poll for content stability + stop button.

        Override for platforms with custom wait logic.
        """
        deadline = time.time() + timeout_ms / 1000
        last_content = ""
        idle_start = None
        idle_ms = 3000

        while time.time() < deadline:
            # Check stop button (MiMo proposal)
            stop_btn = await self._find_stop_button(page)
            if stop_btn is not None:
                try:
                    if await stop_btn.is_visible(timeout=500):
                        idle_start = None  # still generating
                        await page.wait_for_timeout(500)
                        continue
                except Exception:
                    pass

            # Check content stability
            try:
                current = await self._get_latest_response_text(page)
                if current and current != last_content:
                    last_content = current
                    idle_start = time.time()
                elif current and idle_start and (time.time() - idle_start) * 1000 >= idle_ms:
                    return  # content stable
            except Exception:
                pass

            await page.wait_for_timeout(500)

        if not last_content:
            raise QueryTimeoutError(self.config().platform, timeout_ms)

    async def _try_copy_markdown(self, page: Any) -> str | None:
        """Try to get response as Markdown by clicking the copy button.

        Intercepts clipboard.writeText to capture the Markdown content
        that AI platforms copy when the user clicks "Copy".

        Returns Markdown string if successful, None otherwise.
        """
        # Inject clipboard interceptor
        await page.evaluate("""() => {
            window.__copiedMarkdown = null;
            const originalWrite = navigator.clipboard.writeText;
            navigator.clipboard.writeText = (text) => {
                window.__copiedMarkdown = text;
                return originalWrite.call(navigator.clipboard, text);
            };
        }""")

        # Try to find and click the copy button
        copy_selectors = [
            'button[aria-label="Copy"]',
            'button[aria-label="复制"]',
            'button[aria-label="Copy response"]',
            'button[aria-label="Copy to clipboard"]',
            'button:has(svg[class*="copy"])',
            'button:has-text("Copy")',
            'button:has-text("复制")',
        ]

        for sel in copy_selectors:
            try:
                btn = page.locator(sel).last  # Last = most recent response
                if await btn.is_visible(timeout=500):
                    await btn.click()
                    await page.wait_for_timeout(500)

                    # Read intercepted content
                    markdown = await page.evaluate("() => window.__copiedMarkdown")
                    if markdown and len(markdown) > 10:
                        return markdown
            except Exception:
                continue

        return None

    async def _find_stop_button(self, page: Any) -> Any:
        """Find the 'Stop generating' button. Override for platform-specific selectors."""
        for sel in [
            'button[aria-label="Stop generating"]',
            'button:has-text("Stop")',
            'button:has-text("停止")',
        ]:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=500):
                    return el
            except Exception:
                continue
        return None

    async def _get_latest_response_text(self, page: Any) -> str:
        """Get the latest response text. Override for platform-specific selectors."""
        try:
            body = await page.locator("body").inner_text(timeout=3000)
            return body[-500:] if body else ""  # last 500 chars for stability check
        except Exception:
            return ""

    # ── Bridge: extract_result (from contracts.QueryAdapter ABC) ──

    async def extract_result(self, page: Any) -> dict[str, Any]:
        """Extract the AI's response from the page DOM.

        Delegates to ``_extract_response()`` which subclasses implement.
        """
        try:
            text = await self._extract_response(page, "", 30000)
            return {
                "content": text,
                "images": [],
                "thinking": None,
                "model": None,
            }
        except TimeoutError:
            return {
                "content": None,
                "images": [],
                "thinking": None,
                "model": None,
            }

    # ── Utility ────────────────────────────────────────────

    def _is_ui_element(self, text: str) -> bool:
        """Check if text is a UI element to skip. Override for platform-specific elements."""
        return len(text) < 2

    async def abort_current(self, page: Any) -> None:
        """Abort current response generation by clicking Stop."""
        stop_btn = await self._find_stop_button(page)
        if stop_btn is not None:
            try:
                await stop_btn.click()
                await page.wait_for_timeout(1000)
            except Exception:
                pass
