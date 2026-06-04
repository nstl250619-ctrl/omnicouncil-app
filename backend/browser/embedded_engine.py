"""EmbeddedEngine — per-AI persistent context browser engine.

Core design: each AI has its own persistent profile directory.
Login and work share the SAME profile, so cookies auto-persist.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable

from .engine import BrowserEngine, EngineMode, EngineStatus, AuthStatus, PageInfo

logger = logging.getLogger(__name__)


class EmbeddedEngine(BrowserEngine):
    """Browser engine with per-AI persistent contexts.

    Key design:
    - Each AI gets its own profile directory ({ai_id}_profile)
    - Login browser and work browser share the SAME profile
    - Login success = cookies exist in profile directory
    - No cookie copying needed
    """

    def __init__(self, auth_dir: str | None = None, headless: bool = True):
        self._auth_dir = auth_dir or str(Path.home() / ".omnicouncil" / "auth")
        self._headless = headless
        self._playwright = None
        self._contexts: dict[str, Any] = {}  # ai_id -> persistent context
        self._pages: dict[str, Any] = {}     # ai_id -> page
        self._connected = False
        self._authenticated: set[str] = set()

    @property
    def mode(self) -> EngineMode:
        return EngineMode.EMBEDDED

    def _get_profile_dir(self, ai_id: str) -> str:
        """Get the persistent profile directory for an AI."""
        return str(Path(self._auth_dir) / f"{ai_id}_profile")

    async def connect(self) -> bool:
        """Launch Playwright (no browser yet — created per-AI on demand)."""
        try:
            from patchright.async_api import async_playwright
            self._playwright = await async_playwright().start()
            self._connected = True
            logger.info("Embedded: Playwright connected")

            # Check which AIs have saved sessions
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
        """Close all contexts and cleanup."""
        for ai_id in list(self._pages.keys()):
            await self.close_page(ai_id)

        for ai_id, ctx in list(self._contexts.items()):
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
        logger.info("Embedded: Disconnected")

    async def is_connected(self) -> bool:
        return self._connected and self._playwright is not None

    async def _get_context(self, ai_id: str) -> Any:
        """Get or create a persistent context for the given AI."""
        if ai_id in self._contexts:
            return self._contexts[ai_id]

        profile_dir = self._get_profile_dir(ai_id)
        Path(profile_dir).mkdir(parents=True, exist_ok=True)

        logger.info("Creating persistent context for %s at %s", ai_id, profile_dir)
        ctx = await self._playwright.chromium.launch_persistent_context(
            profile_dir,
            headless=self._headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        self._contexts[ai_id] = ctx
        return ctx

    async def get_page(self, ai_id: str, url: str) -> Any:
        """Get or create a page for the given AI using its persistent context."""
        if not self._connected:
            raise RuntimeError("Browser not connected")

        # Return existing page if alive
        if ai_id in self._pages:
            page = self._pages[ai_id]
            try:
                _ = page.url
                return page
            except Exception:
                del self._pages[ai_id]

        # Create page from AI's persistent context
        ctx = await self._get_context(ai_id)
        page = await ctx.new_page()

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)
        except Exception as e:
            logger.warning("Failed to navigate to %s: %s", url, e)

        self._pages[ai_id] = page
        logger.info("Created page for %s at %s", ai_id, url)
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
            if ai_id == "deepseek":
                if "/sign_in" in url:
                    return AuthStatus.NOT_LOGGED_IN
            elif ai_id == "qianwen":
                if "login" in url.lower():
                    return AuthStatus.NOT_LOGGED_IN
        except Exception:
            pass
        return AuthStatus.AUTHENTICATED

    async def login(self, ai_id: str, url: str) -> tuple[bool, str]:
        """Launch visible browser for manual login.

        Uses the SAME profile directory as the work engine.
        User logs in, closes browser → cookies auto-persisted.
        """
        debug_log = os.path.join(self._auth_dir, "login_debug.log")
        os.makedirs(os.path.dirname(debug_log), exist_ok=True)

        def debug(msg: str):
            logger.info(msg)
            with open(debug_log, "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")

        debug(f"=== Login for {ai_id} at {url} ===")

        profile_dir = self._get_profile_dir(ai_id)
        Path(profile_dir).mkdir(parents=True, exist_ok=True)
        debug(f"Profile: {profile_dir}")

        # Close existing context for this AI (if any)
        if ai_id in self._contexts:
            try:
                await self._contexts[ai_id].close()
            except Exception:
                pass
            del self._contexts[ai_id]
            self._pages.pop(ai_id, None)

        browser = None
        try:
            debug("Launching visible browser with persistent context...")
            browser = await self._playwright.chromium.launch_persistent_context(
                profile_dir,
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
            )
            debug("Browser launched")

            page = browser.pages[0] if browser.pages else await browser.new_page()

            # Track browser close
            disconnected = asyncio.Event()
            browser.on("disconnected", lambda _: disconnected.set())

            debug(f"Navigating to {url}...")
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            debug("Navigation complete, waiting for user to close browser...")

            # Wait for user to close browser
            await disconnected.wait()
            debug("Browser closed by user")

            # Check if cookies were saved
            if self._has_saved_cookies(ai_id):
                self._authenticated.add(ai_id)
                debug(f"Login successful for {ai_id} (cookies found)")
                return True, ""
            else:
                debug(f"Login not detected for {ai_id} (no cookies)")
                return False, "未检测到登录状态，请确保已完成登录"

        except Exception as e:
            import traceback
            error_msg = f"{type(e).__name__}: {str(e)}"
            debug(f"ERROR: {error_msg}")
            debug(f"TRACEBACK:\n{traceback.format_exc()}")
            return False, error_msg
        finally:
            if browser:
                try:
                    if browser.is_connected():
                        await browser.close()
                except Exception:
                    pass

    def _has_saved_cookies(self, ai_id: str) -> bool:
        """Check if there are saved cookies for this AI."""
        profile_dir = Path(self._get_profile_dir(ai_id))
        cookie_file = profile_dir / "Default" / "Cookies"
        return cookie_file.exists() and cookie_file.stat().st_size > 0

    def _is_on_ai_page(self, ai_id: str, url: str) -> bool:
        """Check if the URL is on the AI's domain (not just landing page)."""
        if ai_id == "deepseek":
            return "chat.deepseek.com" in url and "/sign_in" not in url
        elif ai_id == "qianwen":
            # qianwen.aliyun.com, www.qianwen.com, tongyi.aliyun.com
            is_qianwen_domain = "qianwen" in url or "tongyi.aliyun.com" in url
            is_not_login = "login" not in url.lower() and "sign" not in url.lower()
            return is_qianwen_domain and is_not_login
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
            mode=EngineMode.EMBEDDED,
            connected=self._connected,
            browser_version="persistent",
            active_pages=pages,
        )

    async def save_auth_state(self, ai_id: str) -> bool:
        """No-op: persistent context auto-saves."""
        return True

    async def load_auth_state(self, ai_id: str) -> bool:
        """No-op: persistent context auto-loads."""
        return True

    async def ensure_logged_in(self, ai_id: str, on_login_required: Callable | None = None) -> bool:
        return self.is_authenticated(ai_id)
