"""EmbeddedEngine — persistent context browser engine.

Core design: login and work share the SAME persistent context profile.
This ensures cookies, localStorage, IndexedDB are all automatically shared.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
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
        """Launch visible browser for manual login."""
        import traceback as tb
        import sys

        # Use fixed path for debug log
        debug_log = "C:\\Users\\green\\.omnicouncil\\login_debug.log"
        os.makedirs(os.path.dirname(debug_log), exist_ok=True)

        def debug(msg: str):
            """Write to both logger and file."""
            logger.info(msg)
            with open(debug_log, "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")

        debug(f"=== Login attempt for {ai_id} ===")
        debug(f"URL: {url}")
        debug(f"Python: {sys.executable}")
        debug(f"HOME: {Path.home()}")
        debug(f"LOCALAPPDATA: {os.environ.get('LOCALAPPDATA', 'NOT SET')}")

        profile_dir = self._get_profile_dir(ai_id)
        Path(profile_dir).mkdir(parents=True, exist_ok=True)
        debug(f"Profile dir: {profile_dir}")

        # Check if patchright browser is installed
        try:
            from patchright.async_api import async_playwright
            pw = await async_playwright().start()
            browser_path = pw.chromium.executable_path
            debug(f"Chromium path: {browser_path}")
            await pw.stop()
        except Exception as e:
            debug(f"Patchright check failed: {e}")

        # Create fresh playwright for login (don't reuse main instance)
        pw = None
        browser = None
        is_alive = True

        try:
            debug("Creating Playwright instance...")
            pw = await async_playwright().start()

            debug("Launching persistent context (headless=False)...")
            browser = await pw.chromium.launch_persistent_context(
                profile_dir,
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
            )
            debug("Browser launched successfully")

            page = browser.pages[0] if browser.pages else await browser.new_page()

            # Track if user closes browser manually
            def on_close(_):
                nonlocal is_alive
                is_alive = False

            page.on("close", on_close)

            debug(f"Navigating to {url}...")
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            debug(f"Navigation complete, waiting for login...")

            # Wait for login
            max_wait = 300
            start = time.time()

            while time.time() - start < max_wait:
                await asyncio.sleep(2)

                if not is_alive:
                    debug("User closed browser")
                    return False, "用户关闭了浏览器窗口"

                try:
                    logged_in = await self._check_login(ai_id, page)
                    if logged_in:
                        self._authenticated.add(ai_id)
                        debug(f"Login successful for {ai_id}")
                        return True, ""
                except Exception as check_err:
                    debug(f"Login check error: {check_err}")

            debug("Login timeout")
            return False, "登录超时（5分钟）"

        except Exception as e:
            import traceback as tb
            error_msg = f"{type(e).__name__}: {str(e)}"
            trace = tb.format_exc()
            debug(f"ERROR: {error_msg}")
            debug(f"TRACEBACK:\n{trace}")
            return False, error_msg
        finally:
            if browser:
                try:
                    if browser.is_connected():
                        await browser.close()
                except Exception:
                    pass
            if pw:
                try:
                    await pw.stop()
                except Exception:
                    pass

    async def _check_login(self, ai_id: str, page: Any) -> bool:
        """Check if login is complete."""
        url = page.url

        if ai_id == "deepseek":
            # DeepSeek: logged in if not on sign_in page and on chat page
            if "/sign_in" in url:
                return False
            if "chat.deepseek.com" in url and "/sign_in" not in url:
                return True
            return False

        elif ai_id == "qianwen":
            # Qianwen: multiple detection strategies
            # 1. Check URL - if we're on a chat page, we're logged in
            if "qianwen.com" in url and "login" not in url.lower():
                return True
            if "tongyi.aliyun.com" in url and "login" not in url.lower():
                return True

            # 2. Check for chat input elements
            try:
                for sel in ["textarea", "[contenteditable='true']", "[role='textbox']"]:
                    el = page.locator(sel).first
                    if await el.count() > 0 and await el.is_visible(timeout=500):
                        return True
            except Exception:
                pass

            # 3. Check for user avatar or profile (logged in indicator)
            try:
                avatar = page.locator("[class*='avatar'], [class*='user'], [class*='profile']")
                if await avatar.count() > 0:
                    return True
            except Exception:
                pass

        return False

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
