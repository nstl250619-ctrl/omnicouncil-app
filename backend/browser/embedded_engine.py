"""EmbeddedEngine — launches and manages an embedded Chromium browser."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable

from .engine import BrowserEngine, EngineMode, EngineStatus, AuthStatus, PageInfo

logger = logging.getLogger(__name__)


class EmbeddedEngine(BrowserEngine):
    """Launches an embedded Chromium browser.

    Uses storage_state for auth persistence.
    First launch requires manual login; subsequent launches restore session.
    """

    def __init__(self, auth_dir: str | None = None, headless: bool = True):
        self._auth_dir = auth_dir or str(Path.home() / ".omnicouncil" / "auth")
        self._headless = headless
        self._playwright = None
        self._browser = None
        self._context = None
        self._pages: dict[str, Any] = {}
        self._connected = False

    @property
    def mode(self) -> EngineMode:
        return EngineMode.EMBEDDED

    def _get_auth_path(self, ai_id: str) -> Path:
        """Get the auth state file path for an AI."""
        return Path(self._auth_dir) / f"{ai_id}.json"

    async def connect(self) -> bool:
        """Launch embedded Chromium."""
        try:
            from patchright.async_api import async_playwright

            logger.info("Embedded: Launching Chromium (headless=%s)", self._headless)
            self._playwright = await async_playwright().start()

            # Launch browser
            self._browser = await self._playwright.chromium.launch(
                headless=self._headless,
                args=["--disable-blink-features=AutomationControlled"],
            )

            self._connected = True
            logger.info("Embedded: Chromium launched successfully")
            return True

        except Exception as e:
            logger.error("Embedded: Failed to launch Chromium: %s", e)
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Close browser and cleanup."""
        for ai_id in list(self._pages.keys()):
            await self.close_page(ai_id)

        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None

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
        logger.info("Embedded: Disconnected")

    async def is_connected(self) -> bool:
        """Check if browser is still running."""
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
            raise RuntimeError("Browser not connected")

        # Return existing page if available
        if ai_id in self._pages:
            page = self._pages[ai_id]
            try:
                _ = page.url
                return page
            except Exception:
                del self._pages[ai_id]

        # Create context with auth state if available
        auth_path = self._get_auth_path(ai_id)
        context_options = {}

        if auth_path.exists():
            try:
                context_options["storage_state"] = str(auth_path)
                logger.info("Embedded: Loading auth state for %s", ai_id)
            except Exception as e:
                logger.warning("Embedded: Failed to load auth state for %s: %s", ai_id, e)

        # Create or reuse context
        if not self._context:
            self._context = await self._browser.new_context(**context_options)
        elif context_options:
            # Need a new context with different auth state
            await self._context.close()
            self._context = await self._browser.new_context(**context_options)

        page = await self._context.new_page()

        # Navigate to AI website
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)
        except Exception as e:
            logger.warning("Embedded: Failed to navigate to %s: %s", url, e)

        self._pages[ai_id] = page
        logger.info("Embedded: Created page for %s at %s", ai_id, url)
        return page

    async def close_page(self, ai_id: str) -> None:
        """Close a specific AI's page."""
        if ai_id in self._pages:
            try:
                await self._pages[ai_id].close()
            except Exception:
                pass
            del self._pages[ai_id]
            logger.info("Embedded: Closed page for %s", ai_id)

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
        """Ensure login is valid. Triggers login window if needed."""
        status = await self.check_auth(ai_id)

        if status == AuthStatus.AUTHENTICATED:
            return True

        if status in (AuthStatus.NOT_LOGGED_IN, AuthStatus.EXPIRED):
            if on_login_required:
                # Launch a visible browser for manual login
                await self._launch_login_window(ai_id, on_login_required)
            return False

        return True

    async def _launch_login_window(self, ai_id: str, on_complete: Callable) -> None:
        """Launch a visible browser window for manual login."""
        logger.info("Embedded: Launching login window for %s", ai_id)

        # Create a new visible browser for login
        try:
            from patchright.async_api import async_playwright

            pw = await async_playwright().start()
            login_browser = await pw.chromium.launch(headless=False)
            login_context = await login_browser.new_context()
            login_page = await login_context.new_page()

            # Navigate to AI website
            url = self._get_ai_url(ai_id)
            await login_page.goto(url, wait_until="domcontentloaded", timeout=30000)

            # Wait for user to complete login (check periodically)
            max_wait = 300  # 5 minutes
            import time
            start = time.time()

            while time.time() - start < max_wait:
                await login_page.wait_for_timeout(2000)

                # Check if login is complete
                auth_status = await self._check_page_auth(login_page, ai_id)
                if auth_status == AuthStatus.AUTHENTICATED:
                    # Save auth state
                    auth_path = self._get_auth_path(ai_id)
                    auth_path.parent.mkdir(parents=True, exist_ok=True)
                    await login_context.storage_state(path=str(auth_path))
                    logger.info("Embedded: Login completed for %s, auth state saved", ai_id)

                    # Copy cookies to main context
                    if self._context:
                        cookies = await login_context.cookies()
                        await self._context.add_cookies(cookies)

                    on_complete(ai_id, True)
                    break

            # Close login browser
            await login_browser.close()
            await pw.stop()

        except Exception as e:
            logger.error("Embedded: Login window failed: %s", e)
            on_complete(ai_id, False)

    async def _check_page_auth(self, page: Any, ai_id: str) -> AuthStatus:
        """Check auth status on a specific page."""
        url = page.url

        if ai_id == "deepseek":
            if "/sign_in" in url:
                return AuthStatus.NOT_LOGGED_IN
        elif ai_id == "qianwen":
            if "login" in url.lower():
                return AuthStatus.NOT_LOGGED_IN

        return AuthStatus.AUTHENTICATED

    def _get_ai_url(self, ai_id: str) -> str:
        """Get the URL for an AI website."""
        urls = {
            "deepseek": "https://chat.deepseek.com",
            "qianwen": "https://tongyi.aliyun.com/qianwen",
            "gemini": "https://gemini.google.com",
        }
        return urls.get(ai_id, "https://example.com")

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
            mode=EngineMode.EMBEDDED,
            connected=self._connected,
            browser_version=self._browser.version if self._browser else "unknown",
            active_pages=pages,
        )

    async def save_auth_state(self, ai_id: str) -> bool:
        """Save current auth state to file."""
        if ai_id not in self._pages or not self._context:
            return False

        try:
            auth_path = self._get_auth_path(ai_id)
            auth_path.parent.mkdir(parents=True, exist_ok=True)
            await self._context.storage_state(path=str(auth_path))
            logger.info("Embedded: Saved auth state for %s", ai_id)
            return True
        except Exception as e:
            logger.error("Embedded: Failed to save auth state for %s: %s", ai_id, e)
            return False

    async def load_auth_state(self, ai_id: str) -> bool:
        """Load saved auth state from file."""
        auth_path = self._get_auth_path(ai_id)
        if not auth_path.exists():
            return False

        try:
            if self._context:
                cookies = json.loads(auth_path.read_text()).get("cookies", [])
                await self._context.add_cookies(cookies)
                logger.info("Embedded: Loaded auth state for %s", ai_id)
                return True
        except Exception as e:
            logger.error("Embedded: Failed to load auth state for %s: %s", ai_id, e)

        return False
