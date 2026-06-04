"""EmbeddedEngine — persistent context browser engine.

Core design: login and work share the SAME persistent context profile.
This ensures cookies, localStorage, IndexedDB are all automatically shared.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Callable

from .engine import BrowserEngine, EngineMode, EngineStatus, AuthStatus, PageInfo

logger = logging.getLogger(__name__)


class EmbeddedEngine(BrowserEngine):
    """Browser engine using Playwright persistent context.

    Key design: ONE profile directory per AI, shared between login and work.
    This eliminates the "two contexts" problem where cookies don't transfer.
    """

    def __init__(self, auth_dir: str | None = None, headless: bool = True):
        self._auth_dir = auth_dir or str(Path.home() / ".omnicouncil" / "auth")
        self._headless = headless
        self._playwright = None
        self._browser = None  # Persistent context (not a plain browser)
        self._pages: dict[str, Any] = {}
        self._connected = False
        self._authenticated: set[str] = set()

    @property
    def mode(self) -> EngineMode:
        return EngineMode.EMBEDDED

    def _get_profile_dir(self, ai_id: str) -> str:
        """Get the persistent profile directory for an AI."""
        return str(Path(self._auth_dir) / f"{ai_id}_profile")

    async def connect(self) -> bool:
        """Launch persistent context browser."""
        try:
            from patchright.async_api import async_playwright

            logger.info("Embedded: Launching persistent Chromium (headless=%s)", self._headless)
            self._playwright = await async_playwright().start()

            # Use a default profile for the main context
            default_profile = str(Path(self._auth_dir) / "default_profile")
            Path(default_profile).mkdir(parents=True, exist_ok=True)

            self._browser = await self._playwright.chromium.launch_persistent_context(
                default_profile,
                headless=self._headless,
                args=["--disable-blink-features=AutomationControlled"],
            )

            self._connected = True
            logger.info("Embedded: Persistent context launched successfully")
            return True

        except Exception as e:
            logger.error("Embedded: Failed to launch: %s", e)
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Close browser and cleanup."""
        for ai_id in list(self._pages.keys()):
            await self.close_page(ai_id)

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
        if not self._connected or not self._browser:
            return False
        try:
            _ = self._browser.pages
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

        # Create new page in the persistent context
        page = await self._browser.new_page()

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)
        except Exception as e:
            logger.warning("Embedded: Failed to navigate to %s: %s", url, e)

        self._pages[ai_id] = page
        logger.info("Embedded: Created page for %s at %s", ai_id, url)
        return page

    async def close_page(self, ai_id: str) -> None:
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

    async def login(self, ai_id: str, url: str) -> tuple[bool, str]:
        """Launch visible browser for manual login.

        Returns (success: bool, error_message: str).
        Uses the SAME profile directory as the main engine,
        so cookies/localStorage are automatically shared.
        """
        logger.info("Embedded: Launching login window for %s at %s", ai_id, url)

        profile_dir = self._get_profile_dir(ai_id)
        Path(profile_dir).mkdir(parents=True, exist_ok=True)
        logger.info("Embedded: Profile dir: %s", profile_dir)

        # Reuse the main Playwright instance to avoid conflicts
        if not self._playwright:
            logger.info("Embedded: Creating new Playwright instance")
            from patchright.async_api import async_playwright
            self._playwright = await async_playwright().start()

        browser = None
        is_alive = True

        try:
            logger.info("Embedded: Launching persistent context (headless=False)")
            browser = await self._playwright.chromium.launch_persistent_context(
                profile_dir,
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
            )
            logger.info("Embedded: Browser launched successfully")

            page = browser.pages[0] if browser.pages else await browser.new_page()

            # Track if user closes browser manually
            def on_close(_):
                nonlocal is_alive
                is_alive = False

            page.on("close", on_close)

            logger.info("Embedded: Navigating to %s", url)
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            logger.info("Embedded: Navigation complete, waiting for login...")

            # Wait for login
            max_wait = 300
            start = time.time()

            while time.time() - start < max_wait:
                await asyncio.sleep(2)

                if not is_alive:
                    logger.info("User closed browser for %s", ai_id)
                    return False, "用户关闭了浏览器窗口"

                try:
                    logged_in = await self._check_login(ai_id, page)
                    if logged_in:
                        self._authenticated.add(ai_id)
                        logger.info("Login successful for %s", ai_id)
                        return True, ""
                except Exception:
                    pass

            logger.warning("Login timeout for %s", ai_id)
            return False, "登录超时（5分钟）"

        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
            logger.exception("Login error for %s: %s", ai_id, error_msg)
            return False, error_msg
        finally:
            if browser:
                try:
                    if browser.is_connected():
                        await browser.close()
                except Exception:
                    pass

    async def _check_login(self, ai_id: str, page: Any) -> bool:
        """Check if login is complete."""
        url = page.url

        if ai_id == "deepseek":
            return "/sign_in" not in url and "chat" in url

        elif ai_id == "qianwen":
            # Check for textarea (chat input) as login indicator
            try:
                textarea = page.locator("textarea, [contenteditable='true']")
                if await textarea.count() > 0 and await textarea.first.is_visible(timeout=1000):
                    return True
            except Exception:
                pass
            # Fallback: check URL
            if "login" not in url and "sign" not in url:
                if "qianwen" in url or "tongyi" in url:
                    return True

        return False

    def is_authenticated(self, ai_id: str) -> bool:
        return ai_id in self._authenticated

    async def get_status(self) -> EngineStatus:
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
                    ai_id=ai_id, url="", title="",
                    is_logged_in=False, auth_status=AuthStatus.UNKNOWN,
                ))

        return EngineStatus(
            mode=EngineMode.EMBEDDED,
            connected=self._connected,
            browser_version=self._browser.version if self._browser else "unknown",
            active_pages=pages,
        )

    async def save_auth_state(self, ai_id: str) -> bool:
        """No-op: persistent context auto-saves."""
        return True

    async def load_auth_state(self, ai_id: str) -> bool:
        """No-op: persistent context auto-loads."""
        return True

    async def ensure_logged_in(self, ai_id: str, on_login_required: Callable | None = None) -> bool:
        """Not used in new architecture — login is handled by handle_reauth."""
        return self.is_authenticated(ai_id)
