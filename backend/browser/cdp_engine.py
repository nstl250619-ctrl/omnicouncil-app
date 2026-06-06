"""CDPEngine — connects to local Chrome via Chrome DevTools Protocol."""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .engine import AuthStatus, BrowserEngine, EngineMode, EngineStatus, PageInfo

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


class CDPEngine(BrowserEngine):
    """Connects to a locally running Chrome instance via CDP.

    Chrome must be started with: chrome --remote-debugging-port=9222

    Benefits:
    - Zero login cost (reuses user's existing Chrome session)
    - Automatic Cloudflare bypass (real browser)
    - All cookies/extensions available
    """

    def __init__(self, cdp_url: str = "http://localhost:9222", auth_dir: str | None = None):
        self._cdp_url = cdp_url
        self._auth_dir = auth_dir or str(Path.home() / ".omnicouncil" / "auth")
        self._browser = None
        self._context = None
        self._pages: dict[str, Any] = {}  # ai_id -> page
        self._connected = False

    @property
    def mode(self) -> EngineMode:
        return EngineMode.CDP

    async def connect(self) -> bool:
        """Connect to local Chrome via CDP."""
        try:
            from patchright.async_api import async_playwright

            logger.info("CDP: Connecting to %s", self._cdp_url)
            pw = await async_playwright().start()
            self._browser = await pw.chromium.connect_over_cdp(self._cdp_url)
            self._connected = True

            # Get existing context or create new one
            contexts = self._browser.contexts
            if contexts:
                self._context = contexts[0]
            else:
                self._context = await self._browser.new_context()

            logger.info("CDP: Connected successfully. Contexts: %d", len(contexts))
            return True

        except Exception as e:
            logger.error("CDP: Connection failed: %s", e)
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Disconnect from Chrome (does NOT close Chrome)."""
        for ai_id in list(self._pages.keys()):
            await self.close_page(ai_id)

        # Don't close the browser - it's the user's Chrome

        self._browser = None
        self._context = None
        self._connected = False
        logger.info("CDP: Disconnected")

    async def is_connected(self) -> bool:
        """Check if CDP connection is alive."""
        if not self._connected or not self._browser:
            return False
        try:
            # Try to access browser version
            _ = self._browser.version
            return True
        except Exception:
            self._connected = False
            return False

    async def get_page(self, ai_id: str, url: str) -> Any:
        """Get or create a page for the given AI."""
        if not self._connected:
            raise RuntimeError("Not connected to Chrome")

        # Return existing page if available
        if ai_id in self._pages:
            page = self._pages[ai_id]
            try:
                # Check if page is still alive
                _ = page.url
                return page
            except Exception:
                # Page was closed, remove it
                del self._pages[ai_id]

        # Create new page
        if not self._context:
            self._context = await self._browser.new_context()

        page = await self._context.new_page()

        # Navigate to AI website
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)
        except Exception as e:
            logger.warning("CDP: Failed to navigate to %s: %s", url, e)

        self._pages[ai_id] = page
        logger.info("CDP: Created page for %s at %s", ai_id, url)
        return page

    async def close_page(self, ai_id: str) -> None:
        """Close a specific AI's page."""
        if ai_id in self._pages:
            with contextlib.suppress(Exception):
                await self._pages[ai_id].close()
            del self._pages[ai_id]
            logger.info("CDP: Closed page for %s", ai_id)

    async def check_auth(self, ai_id: str) -> AuthStatus:
        """Check if the user is logged in for the given AI."""
        if ai_id not in self._pages:
            return AuthStatus.UNKNOWN

        page = self._pages[ai_id]
        url = page.url

        # AI-specific auth checks
        if ai_id == "deepseek":
            if "/sign_in" in url:
                return AuthStatus.NOT_LOGGED_IN
            # Check for login elements
            try:
                body = await page.locator("body").inner_text(timeout=3000)
                if "登录" in body[:200] or "sign in" in body[:200].lower():
                    return AuthStatus.NOT_LOGGED_IN
            except Exception:
                pass

        elif ai_id == "qianwen":
            if "login" in url.lower():
                return AuthStatus.NOT_LOGGED_IN
            try:
                body = await page.locator("body").inner_text(timeout=3000)
                if "登录" in body[:200]:
                    return AuthStatus.NOT_LOGGED_IN
            except Exception:
                pass

        return AuthStatus.AUTHENTICATED

    async def ensure_logged_in(self, ai_id: str, on_login_required: Callable | None = None) -> bool:
        """Ensure login is valid."""
        status = await self.check_auth(ai_id)

        if status == AuthStatus.AUTHENTICATED:
            return True

        if status in (AuthStatus.NOT_LOGGED_IN, AuthStatus.EXPIRED):
            if on_login_required:
                on_login_required(ai_id, status)
            return False

        return True

    async def get_status(self) -> EngineStatus:
        """Get current engine status."""
        pages = []
        for ai_id, page in self._pages.items():
            try:
                auth = await self.check_auth(ai_id)
                pages.append(PageInfo(
                    ai_id=ai_id,
                    url=page.url,
                    title=await page.title(),
                    is_logged_in=auth == AuthStatus.AUTHENTICATED,
                    auth_status=auth,
                ))
            except Exception:
                pages.append(PageInfo(
                    ai_id=ai_id,
                    url="",
                    title="",
                    is_logged_in=False,
                    auth_status=AuthStatus.UNKNOWN,
                ))

        return EngineStatus(
            mode=EngineMode.CDP,
            connected=self._connected,
            browser_version=self._browser.version if self._browser else "unknown",
            active_pages=pages,
        )

    async def save_auth_state(self, ai_id: str) -> bool:
        """CDP mode doesn't need to save auth state - it uses Chrome's own cookies."""
        return True

    async def load_auth_state(self, ai_id: str) -> bool:
        """CDP mode doesn't need to load auth state - it uses Chrome's own cookies."""
        return True
