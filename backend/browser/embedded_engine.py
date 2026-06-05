"""EmbeddedEngine — per-AI persistent context browser engine.

Core design:
- Each AI has its own persistent profile directory
- Login and work share the SAME profile (cookies auto-persist)
- Login success = cookies exist in profile directory
- No cookie copying, no complex URL detection
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
    """Browser engine with per-AI persistent contexts."""

    def __init__(self, auth_dir: str | None = None, headless: bool = True):
        self._auth_dir = auth_dir or str(Path.home() / ".omnicouncil" / "auth")
        self._headless = headless
        self._playwright = None
        self._contexts: dict[str, Any] = {}
        self._pages: dict[str, Any] = {}
        self._connected = False
        self._authenticated: set[str] = set()

    @property
    def mode(self) -> EngineMode:
        return EngineMode.EMBEDDED

    def _get_profile_dir(self, ai_id: str) -> str:
        return str(Path(self._auth_dir) / f"{ai_id}_profile")

    async def connect(self) -> bool:
        try:
            from patchright.async_api import async_playwright
            self._playwright = await async_playwright().start()
            self._connected = True
            logger.info("Embedded: Playwright connected")

            # Check for saved sessions
            for ai_id in ["deepseek", "qianwen", "gemini", "chatgpt", "claude"]:
                if self._has_saved_cookies(ai_id):
                    self._authenticated.add(ai_id)
                    logger.info("Found saved session for %s", ai_id)

            return True
        except Exception as e:
            logger.error("Embedded: Failed to connect: %s", e)
            self._connected = False
            return False

    async def disconnect(self) -> None:
        for ai_id in list(self._pages.keys()):
            await self.close_page(ai_id)
        for ctx in self._contexts.values():
            try:
                await ctx.close()
            except Exception:
                pass
        self._contexts.clear()
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None
        self._connected = False

    async def is_connected(self) -> bool:
        return self._connected and self._playwright is not None

    async def _get_context(self, ai_id: str) -> Any:
        """Get or create persistent context for this AI."""
        if ai_id in self._contexts:
            return self._contexts[ai_id]

        profile_dir = self._get_profile_dir(ai_id)
        Path(profile_dir).mkdir(parents=True, exist_ok=True)

        ctx = await self._playwright.chromium.launch_persistent_context(
            profile_dir,
            headless=self._headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        self._contexts[ai_id] = ctx
        return ctx

    async def get_page(self, ai_id: str, url: str) -> Any:
        if not self._connected:
            raise RuntimeError("Browser not connected")

        if ai_id in self._pages:
            page = self._pages[ai_id]
            try:
                _ = page.url
                return page
            except Exception:
                del self._pages[ai_id]

        ctx = await self._get_context(ai_id)
        page = await ctx.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)
        except Exception as e:
            logger.warning("Failed to navigate to %s: %s", url, e)

        self._pages[ai_id] = page
        return page

    async def close_page(self, ai_id: str) -> None:
        if ai_id in self._pages:
            try:
                await self._pages[ai_id].close()
            except Exception:
                pass
            del self._pages[ai_id]

    async def check_auth(self, ai_id: str) -> AuthStatus:
        if ai_id not in self._pages:
            return AuthStatus.UNKNOWN
        page = self._pages[ai_id]
        try:
            url = page.url
            if ai_id == "deepseek" and "/sign_in" in url:
                return AuthStatus.NOT_LOGGED_IN
            if ai_id == "qianwen" and "login" in url.lower():
                return AuthStatus.NOT_LOGGED_IN
        except Exception:
            pass
        return AuthStatus.AUTHENTICATED

    async def login(self, ai_id: str, url: str) -> tuple[bool, str]:
        """Launch visible browser for manual login.

        Uses the SAME profile as the work engine.
        User closes browser → cookies auto-persisted → login detected.
        """
        logger.info("Login: %s at %s", ai_id, url)

        profile_dir = self._get_profile_dir(ai_id)
        Path(profile_dir).mkdir(parents=True, exist_ok=True)

        # Close existing context for this AI
        if ai_id in self._contexts:
            try:
                await self._contexts[ai_id].close()
            except Exception:
                pass
            del self._contexts[ai_id]
            self._pages.pop(ai_id, None)

        browser = None
        try:
            browser = await self._playwright.chromium.launch_persistent_context(
                profile_dir,
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
            )

            page = browser.pages[0] if browser.pages else await browser.new_page()

            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            logger.info("Login: waiting for user to close browser...")

            # Poll for browser close (more reliable than disconnected event)
            max_wait = 300  # 5 minutes
            start = time.time()
            browser_closed = False

            while time.time() - start < max_wait:
                await asyncio.sleep(2)
                try:
                    # Check if browser is still connected
                    if not browser.is_connected():
                        browser_closed = True
                        logger.info("Login: browser disconnected")
                        break
                except Exception:
                    browser_closed = True
                    logger.info("Login: browser check failed, assuming closed")
                    break

            if not browser_closed:
                return False, "登录超时（5分钟）"

            # Wait for cookies to flush
            await asyncio.sleep(2)

            # Check if cookies were saved
            if self._has_saved_cookies(ai_id):
                self._authenticated.add(ai_id)
                logger.info("Login successful for %s", ai_id)
                return True, ""

            # Retry check
            await asyncio.sleep(3)
            if self._has_saved_cookies(ai_id):
                self._authenticated.add(ai_id)
                logger.info("Login successful for %s (retry)", ai_id)
                return True, ""

            return False, "未检测到登录状态"

        except Exception as e:
            logger.exception("Login error for %s", ai_id)
            return False, str(e)
        finally:
            if browser:
                try:
                    if browser.is_connected():
                        await browser.close()
                except Exception:
                    pass

    def _has_saved_cookies(self, ai_id: str) -> bool:
        profile_dir = Path(self._get_profile_dir(ai_id))
        cookie_file = profile_dir / "Default" / "Cookies"
        return cookie_file.exists() and cookie_file.stat().st_size > 0

    def _is_on_ai_page(self, ai_id: str, url: str) -> bool:
        if ai_id == "deepseek":
            return "chat.deepseek.com" in url and "/sign_in" not in url
        elif ai_id == "qianwen":
            is_domain = "qianwen" in url or "tongyi.aliyun.com" in url
            is_landing = url in (
                "https://qianwen.aliyun.com/", "https://www.qianwen.com/",
                "https://tongyi.aliyun.com/", "https://tongyi.aliyun.com",
            )
            is_login = "login" in url.lower() or "sign" in url.lower()
            return is_domain and not is_landing and not is_login
        return False

    def is_authenticated(self, ai_id: str) -> bool:
        return ai_id in self._authenticated

    async def get_status(self) -> EngineStatus:
        pages = []
        for ai_id, page in self._pages.items():
            try:
                auth = await self.check_auth(ai_id)
                pages.append(PageInfo(
                    ai_id=ai_id, url=page.url, title=await page.title(),
                    is_logged_in=auth == AuthStatus.AUTHENTICATED, auth_status=auth,
                ))
            except Exception:
                pages.append(PageInfo(
                    ai_id=ai_id, url="", title="",
                    is_logged_in=False, auth_status=AuthStatus.UNKNOWN,
                ))
        return EngineStatus(
            mode=EngineMode.EMBEDDED, connected=self._connected,
            browser_version="persistent", active_pages=pages,
        )

    async def save_auth_state(self, ai_id: str) -> bool:
        return True

    async def load_auth_state(self, ai_id: str) -> bool:
        return True

    async def ensure_logged_in(self, ai_id: str, on_login_required: Callable | None = None) -> bool:
        return self.is_authenticated(ai_id)
