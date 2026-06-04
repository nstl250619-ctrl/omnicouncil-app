"""EmbeddedEngine — persistent context browser engine with proper login detection."""

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
    """Browser engine using Playwright persistent context."""

    def __init__(self, auth_dir: str | None = None, headless: bool = True):
        self._auth_dir = auth_dir or str(Path.home() / ".omnicouncil" / "auth")
        self._headless = headless
        self._playwright = None
        self._browser = None
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
            default_profile = str(Path(self._auth_dir) / "default_profile")
            Path(default_profile).mkdir(parents=True, exist_ok=True)
            self._browser = await self._playwright.chromium.launch_persistent_context(
                default_profile, headless=self._headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            self._connected = True
            logger.info("Embedded: Connected (headless=%s)", self._headless)
            return True
        except Exception as e:
            logger.error("Embedded: Failed to connect: %s", e)
            self._connected = False
            return False

    async def disconnect(self) -> None:
        for ai_id in list(self._pages.keys()):
            await self.close_page(ai_id)
        if self._browser:
            try: await self._browser.close()
            except: pass
            self._browser = None
        if self._playwright:
            try: await self._playwright.stop()
            except: pass
            self._playwright = None
        self._connected = False

    async def is_connected(self) -> bool:
        if not self._connected or not self._browser:
            return False
        try:
            _ = self._browser.pages
            return True
        except:
            self._connected = False
            return False

    async def get_page(self, ai_id: str, url: str) -> Any:
        if not self._connected:
            raise RuntimeError("Browser not connected")
        if ai_id in self._pages:
            page = self._pages[ai_id]
            try:
                _ = page.url
                return page
            except:
                del self._pages[ai_id]
        page = await self._browser.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)
        except Exception as e:
            logger.warning("Failed to navigate to %s: %s", url, e)
        self._pages[ai_id] = page
        return page

    async def close_page(self, ai_id: str) -> None:
        if ai_id in self._pages:
            try: await self._pages[ai_id].close()
            except: pass
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
        except:
            pass
        return AuthStatus.AUTHENTICATED

    async def login(self, ai_id: str, url: str) -> tuple[bool, str]:
        """Launch visible browser for manual login with proper disconnect detection."""
        debug_log = "C:\\Users\\green\\.omnicouncil\\login_debug.log"
        os.makedirs(os.path.dirname(debug_log), exist_ok=True)

        def debug(msg: str):
            logger.info(msg)
            with open(debug_log, "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")

        debug(f"=== Login attempt for {ai_id} ===")
        debug(f"URL: {url}")

        profile_dir = self._get_profile_dir(ai_id)
        Path(profile_dir).mkdir(parents=True, exist_ok=True)
        debug(f"Profile dir: {profile_dir}")

        from patchright.async_api import async_playwright

        pw = None
        browser = None

        try:
            debug("Creating Playwright instance...")
            pw = await async_playwright().start()

            debug("Launching persistent context...")
            browser = await pw.chromium.launch_persistent_context(
                profile_dir, headless=False,
                args=["--disable-blink-features=AutomationControlled"],
            )
            debug("Browser launched")

            page = browser.pages[0] if browser.pages else await browser.new_page()

            # Track browser disconnect (user closes window)
            disconnected = asyncio.Event()
            browser.on("disconnected", lambda _: disconnected.set())

            debug(f"Navigating to {url}...")
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            debug("Navigation complete, waiting for login...")

            # Poll for login
            max_wait = 300
            start = time.time()
            logged_in = False

            while time.time() - start < max_wait:
                # Check if user closed browser
                if disconnected.is_set():
                    debug("Browser disconnected by user")
                    # Check if login was saved before disconnect
                    logged_in = self._check_saved_login(ai_id)
                    debug(f"Saved login check: {logged_in}")
                    break

                # Check login status
                try:
                    logged_in = await self._check_login(ai_id, page)
                    if logged_in:
                        debug("Login detected!")
                        break
                except Exception as e:
                    debug(f"Login check error: {e}")

                await asyncio.sleep(2)

            if not logged_in and not disconnected.is_set():
                debug("Login timeout")
                return False, "登录超时（5分钟）"

            if logged_in:
                # Save auth state
                try:
                    auth_path = str(Path(self._auth_dir) / f"{ai_id}.json")
                    await browser.storage_state(path=auth_path)
                    debug(f"Auth state saved to {auth_path}")
                except Exception as e:
                    debug(f"Failed to save auth state: {e}")

                self._authenticated.add(ai_id)
                debug(f"Login successful for {ai_id}")
                return True, ""
            else:
                debug(f"Login not detected for {ai_id}")
                return False, "登录未完成"

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
                except:
                    pass
            if pw:
                try:
                    await pw.stop()
                except:
                    pass

    def _check_saved_login(self, ai_id: str) -> bool:
        """Check if there's a saved login state (cookies in profile directory)."""
        profile_dir = Path(self._get_profile_dir(ai_id))
        cookie_file = profile_dir / "Default" / "Cookies"
        if cookie_file.exists() and cookie_file.stat().st_size > 0:
            logger.info("Found saved cookies for %s", ai_id)
            self._authenticated.add(ai_id)
            return True
        return False

    async def _check_login(self, ai_id: str, page: Any) -> bool:
        """Check if login is complete."""
        url = page.url

        if ai_id == "deepseek":
            if "/sign_in" in url:
                return False
            if "chat.deepseek.com" in url and "/sign_in" not in url:
                return True
            return False

        elif ai_id == "qianwen":
            # Check URL first
            if "qianwen.com" in url and "login" not in url.lower():
                return True
            if "tongyi.aliyun.com" in url and "login" not in url.lower():
                return True

            # Check for chat input elements
            try:
                for sel in ["textarea", "[contenteditable='true']", "[role='textbox']"]:
                    el = page.locator(sel).first
                    if await el.count() > 0 and await el.is_visible(timeout=500):
                        return True
            except:
                pass

        return False

    async def get_status(self) -> EngineStatus:
        pages = []
        for ai_id, page in self._pages.items():
            try:
                auth = await self.check_auth(ai_id)
                pages.append(PageInfo(
                    ai_id=ai_id, url=page.url, title=await page.title(),
                    is_logged_in=auth == AuthStatus.AUTHENTICATED, auth_status=auth,
                ))
            except:
                pages.append(PageInfo(
                    ai_id=ai_id, url="", title="",
                    is_logged_in=False, auth_status=AuthStatus.UNKNOWN,
                ))
        return EngineStatus(
            mode=EngineMode.EMBEDDED, connected=self._connected,
            browser_version=self._browser.version if self._browser else "unknown",
            active_pages=pages,
        )

    async def save_auth_state(self, ai_id: str) -> bool:
        return True

    async def load_auth_state(self, ai_id: str) -> bool:
        return True

    async def ensure_logged_in(self, ai_id: str, on_login_required: Callable | None = None) -> bool:
        return self.is_authenticated(ai_id)
