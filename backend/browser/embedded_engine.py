"""EmbeddedEngine — per-AI persistent context browser engine."""

from __future__ import annotations

import asyncio
import os
import sys
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import contextlib

from shared.logger import get_logger

from .engine import AuthStatus, BrowserEngine, EngineMode, EngineStatus, PageInfo

if TYPE_CHECKING:
    from collections.abc import Callable

logger = get_logger(__name__)


def _debug(msg: str):
    """Log a debug message via the centralized logger."""
    logger.info(msg)


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
            _debug("Playwright connected")

            for ai_id in ["deepseek", "qianwen", "gemini", "chatgpt", "mimo"]:
                if self._has_saved_cookies(ai_id):
                    self._authenticated.add(ai_id)
                    _debug(f"Found saved session for {ai_id}")

            return True
        except Exception as e:
            _debug(f"Failed to connect: {e}")
            self._connected = False
            return False

    async def disconnect(self) -> None:
        for ai_id in list(self._pages.keys()):
            await self.close_page(ai_id)
        for ctx in self._contexts.values():
            with contextlib.suppress(Exception):
                await ctx.close()
        self._contexts.clear()
        if self._playwright:
            with contextlib.suppress(Exception):
                await self._playwright.stop()
            self._playwright = None
        self._connected = False

    async def is_connected(self) -> bool:
        return self._connected and self._playwright is not None

    async def _get_context(self, ai_id: str) -> Any:
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
            with contextlib.suppress(Exception):
                await self._pages[ai_id].close()
            del self._pages[ai_id]

    async def check_auth(self, ai_id: str) -> AuthStatus:
        if ai_id not in self._pages:
            return AuthStatus.UNKNOWN
        page = self._pages[ai_id]
        try:
            url = page.url
            if ai_id == "deepseek" and "/sign_in" in url:
                return AuthStatus.NOT_LOGGED_IN
            if ai_id == "qianwen":
                # DOM-based: check for visible login button
                login_btns = page.locator('button:has-text("登录"), a:has-text("登录")')
                count = await login_btns.count()
                for i in range(count):
                    btn = login_btns.nth(i)
                    if await btn.is_visible():
                        text = await btn.inner_text()
                        if text.strip() == "登录":
                            return AuthStatus.NOT_LOGGED_IN
        except Exception:
            pass
        return AuthStatus.AUTHENTICATED

    async def login(self, ai_id: str, url: str) -> tuple[bool, str]:
        """Launch visible browser for manual login.

        Uses SAME profile as work engine. User closes browser → check cookies.
        """
        profile_dir = self._get_profile_dir(ai_id)
        Path(profile_dir).mkdir(parents=True, exist_ok=True)

        # Close existing context for this AI
        if ai_id in self._contexts:
            with contextlib.suppress(Exception):
                await self._contexts[ai_id].close()
            del self._contexts[ai_id]
            self._pages.pop(ai_id, None)

        _debug(f"=== Login for {ai_id} at {url} ===")
        _debug(f"Profile: {profile_dir}")

        browser = None
        try:
            _debug("Launching visible browser...")
            browser = await self._playwright.chromium.launch_persistent_context(
                profile_dir,
                headless=False,
                no_viewport=True,  # Gemini: prevents small window
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            _debug("Browser launched")

            page = browser.pages[0] if browser.pages else await browser.new_page()

            # Use page close event to detect user closing the window
            page_closed = asyncio.Event()
            def on_page_close(*args):
                _debug("Page close event fired")
                page_closed.set()
            page.on("close", on_page_close)

            _debug(f"Navigating to {url}...")
            await page.goto(url, wait_until="commit", timeout=45000)
            _debug("Navigation complete, checking if already logged in...")

            # Wait for page to stabilize
            await asyncio.sleep(3)

            # Check if already logged in (from previous session)
            already_logged_in = await self._quick_login_check(ai_id, page)
            if already_logged_in:
                _debug("Already logged in! Saving state...")
                auth_json = Path(self._auth_dir) / f"{ai_id}.json"
                try:
                    await browser.storage_state(path=str(auth_json))
                    _debug(f"Storage state saved to {auth_json}")
                except Exception as e:
                    _debug(f"Failed to save storage state: {e}")
                self._authenticated.add(ai_id)
                _debug(f"LOGIN SUCCESSFUL for {ai_id} (already logged in)")
                with contextlib.suppress(Exception):
                    await browser.close()
                return True, ""

            _debug("Not logged in, waiting for user to close browser...")

            # Wait for user to close browser (page close event or timeout)
            try:
                await asyncio.wait_for(page_closed.wait(), timeout=300)
                _debug("Page closed by user")
            except TimeoutError:
                _debug("Login timeout (5 minutes)")
                return False, "登录超时（5分钟）"

            _debug("Browser closed, saving auth state...")

            # Gemini: explicitly save storage state (cookies + localStorage)
            auth_json = Path(self._auth_dir) / f"{ai_id}.json"
            try:
                await browser.storage_state(path=str(auth_json))
                _debug(f"Storage state saved to {auth_json}")
            except Exception as e:
                _debug(f"Failed to save storage state: {e}")

            # Wait for cookies to flush to disk
            await asyncio.sleep(2)

            # Check cookies
            has_cookies = self._has_saved_cookies(ai_id)
            _debug(f"Cookie check: {has_cookies}")

            if has_cookies:
                self._authenticated.add(ai_id)
                _debug(f"LOGIN SUCCESSFUL for {ai_id}")
                return True, ""

            # Retry
            _debug("Waiting 3 more seconds for cookies...")
            await asyncio.sleep(3)
            has_cookies = self._has_saved_cookies(ai_id)
            _debug(f"Cookie check (retry): {has_cookies}")

            if has_cookies:
                self._authenticated.add(ai_id)
                _debug(f"LOGIN SUCCESSFUL for {ai_id} (retry)")
                return True, ""

            _debug(f"LOGIN FAILED for {ai_id} - no cookies found")
            return False, "未检测到登录状态"

        except Exception as e:
            tb = traceback.format_exc()
            _debug(f"LOGIN ERROR: {e}")
            _debug(f"TRACEBACK:\n{tb}")
            return False, str(e)
        finally:
            if browser:
                try:
                    await browser.close()
                    _debug("Browser closed in finally")
                except Exception as e:
                    _debug(f"Error closing browser: {e}")

    def _has_saved_cookies(self, ai_id: str) -> bool:
        profile_dir = Path(self._get_profile_dir(ai_id))
        # Check both old and new Chromium cookie locations
        cookie_paths = [
            profile_dir / "Default" / "Cookies",
            profile_dir / "Default" / "Network" / "Cookies",
        ]
        for cookie_file in cookie_paths:
            if cookie_file.exists() and cookie_file.stat().st_size > 0:
                _debug(f"Cookie file found: {cookie_file}")
                return True
        _debug(f"No cookies found for {ai_id}")
        return False

    async def _quick_login_check(self, ai_id: str, page: Any) -> bool:
        """Quick check if user is already logged in (from previous session)."""
        try:
            url = page.url
            _debug(f"Quick login check for {ai_id}: {url}")

            if ai_id == "deepseek":
                # DeepSeek: if not on sign_in page, likely logged in
                if "/sign_in" not in url and "chat.deepseek.com" in url:
                    # Verify with textarea
                    textarea = page.locator("textarea")
                    if await textarea.count() > 0 and await textarea.first.is_visible(timeout=1000):
                        return True

            elif ai_id == "qianwen":
                # Qianwen: check for absence of login button (DOM-based)
                if "qianwen" in url:
                    login_btns = page.locator(
                        'button:has-text("登录"), a:has-text("登录")'
                    )
                    count = await login_btns.count()
                    has_visible_login = False
                    for i in range(count):
                        btn = login_btns.nth(i)
                        if await btn.is_visible():
                            text = await btn.inner_text()
                            if text.strip() == "登录":
                                has_visible_login = True
                                break
                    if not has_visible_login:
                        return True

            return False
        except Exception as e:
            _debug(f"Quick login check error: {e}")
            return False

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

    def get_authenticated_ais(self) -> list[str]:
        """Get list of AIs with saved sessions."""
        return list(self._authenticated)

    def check_all_sessions(self) -> dict[str, bool]:
        """Check which AIs have saved cookie sessions."""
        result = {}
        for ai_id in ["deepseek", "qianwen", "gemini", "chatgpt", "mimo"]:
            result[ai_id] = self._has_saved_cookies(ai_id)
        return result

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
