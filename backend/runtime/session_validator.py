"""SessionValidator — offline + online session authentication checks.

Implements the ``SessionValidator`` protocol from ``engine.contracts``.

Check modes (configured via ``PlatformConfig.session_check_mode``):
    - ``"offline"``: Cookie SQLite probe only (fast, no browser).
    - ``"online"``: Navigate to home page + DOM check (slow, needs browser).
    - ``"offline_then_online"`` (default): Try offline first; if
      inconclusive, fall back to online.

The offline check reuses the same SQLite logic as
``ProfileManager._check_cookies`` but operates on a *live* profile
directory (may be updated since boot).

The online check navigates to the platform's home URL and inspects
DOM elements to determine login state.  Platform-specific detection
is delegated to ``OnlineCheckStrategy`` implementations.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from shared.types import SessionState

logger = logging.getLogger(__name__)

# Same config as ProfileManager — shared constant.
_PROVIDER_COOKIE_CONFIG: dict[str, tuple[str, list[str]]] = {
    "deepseek": ("chat.deepseek.com", ["sessionid", "token", "auth"]),
    "qianwen":  ("qianwen.com",       ["sid", "login_", "ALI_", "Session", "cookie2"]),
    "gemini":   ("google.com",        ["SAPISID", "SSID", "__Secure-", "OSID"]),
    "chatgpt":  ("chatgpt.com",       [
        "__Secure-next-auth.session-token",
        "__Host-next-auth.csrf-token",
    ]),
    "mimo":     ("xiaomimimo.com",    ["session", "token", "auth"]),
}

# URL patterns that indicate a login page.
_LOGIN_URL_PATTERNS = [
    "/login", "/signin", "/sign-in", "/sign_in", "/auth/login", "/auth0",
    "accounts.google.com", "login.microsoftonline.com",
]


class OnlineCheckStrategy(ABC):
    """Platform-specific online session check via DOM inspection."""

    @abstractmethod
    async def check(self, page: Any) -> bool:
        """Return True if the page shows a logged-in state."""
        ...


class DefaultOnlineCheck(OnlineCheckStrategy):
    """Default online check: URL-based + input element presence."""

    def __init__(self, platform: str) -> None:
        self._platform = platform

    async def check(self, page: Any) -> bool:
        try:
            url = page.url

            # Check for login page URLs
            for pattern in _LOGIN_URL_PATTERNS:
                if pattern in url.lower():
                    return False

            # Check for Cloudflare challenge
            try:
                title = await page.title()
                if "just a moment" in title.lower() or "cloudflare" in title.lower():
                    return False
            except Exception:
                return False

            # Check for input element (indicates logged-in chat page)
            for selector in ["textarea", "[contenteditable='true']", "[role='textbox']"]:
                try:
                    el = page.locator(selector).first
                    if await el.is_visible(timeout=2000):
                        return True
                except Exception:
                    continue

            return False
        except Exception:
            return False


class QianwenOnlineCheck(OnlineCheckStrategy):
    """千问 DOM-based login detection — checks for visible login button."""

    async def check(self, page: Any) -> bool:
        try:
            url = page.url
            if "login" in url.lower() or "signin" in url.lower():
                return False

            login_btns = page.locator(
                'button:has-text("登录"), a:has-text("登录")'
            )
            count = await login_btns.count()
            for i in range(count):
                btn = login_btns.nth(i)
                if await btn.is_visible():
                    text = await btn.inner_text()
                    if text.strip() == "登录":
                        return False
            return True
        except Exception:
            return False


class ChatGPTOnlineCheck(OnlineCheckStrategy):
    """ChatGPT online check — handles Cloudflare + login redirect."""

    async def check(self, page: Any) -> bool:
        try:
            url = page.url
            if "/auth/login" in url or "auth0.openai.com" in url:
                return False

            title = await page.title()
            if "just a moment" in title.lower() or "cloudflare" in title.lower():
                return False

            # Check for input element
            for selector in ["#prompt-textarea", "[contenteditable='true']", "textarea"]:
                try:
                    el = page.locator(selector).first
                    if await el.is_visible(timeout=2000):
                        return True
                except Exception:
                    continue
            return False
        except Exception:
            return False


# Platform → strategy mapping.
_ONLINE_STRATEGIES: dict[str, type[OnlineCheckStrategy]] = {
    "qianwen": QianwenOnlineCheck,  # no-arg constructor
    "chatgpt": ChatGPTOnlineCheck,  # no-arg constructor
}


class SessionValidator:
    """Concrete ``SessionValidator`` with offline + online checks.

    Parameters
    ----------
    profile_dir:
        Root profile directory (e.g. ``~/.omnicouncil/auth``).
    platform:
        Platform identifier (e.g. ``"deepseek"``).
    mode:
        Check mode: ``"offline"``, ``"online"``, or
        ``"offline_then_online"``.
    home_url:
        URL to navigate to for online checks.  Required when mode
        includes online checking.
    """

    def __init__(
        self,
        profile_dir: Path | str,
        platform: str,
        mode: str = "offline_then_online",
        home_url: str = "",
    ) -> None:
        self._profile_dir = Path(profile_dir)
        self._platform = platform
        self._mode = mode
        self._home_url = home_url

        # Select online check strategy
        strategy_cls = _ONLINE_STRATEGIES.get(platform, DefaultOnlineCheck)
        # QianwenOnlineCheck and ChatGPTOnlineCheck take no args;
        # DefaultOnlineCheck takes platform.
        try:
            self._online_strategy: OnlineCheckStrategy = strategy_cls(platform)
        except TypeError:
            self._online_strategy = strategy_cls()  # type: ignore[call-arg]

    # ── Public API ─────────────────────────────────────────

    async def validate(self, page: Any = None) -> SessionState:
        """Check session validity.

        If *page* is None, only offline check is performed.
        """
        if self._mode == "offline":
            return await self._offline_check()

        if self._mode == "online":
            if page is None:
                return SessionState.UNKNOWN
            return await self._online_check(page)

        # offline_then_online: try offline first
        offline_result = await self._offline_check()
        if offline_result == SessionState.AUTHENTICATED:
            return SessionState.AUTHENTICATED

        # Offline inconclusive — try online if page available
        if page is not None:
            return await self._online_check(page)

        return offline_result

    async def validate_offline(self) -> SessionState:
        """Run only the offline Cookie SQLite probe."""
        return await self._offline_check()

    async def validate_online(self, page: Any) -> SessionState:
        """Run only the online DOM-based check."""
        return await self._online_check(page)

    # ── Offline check (Cookie SQLite) ─────────────────────

    async def _offline_check(self) -> SessionState:
        """Cookie SQLite probe — fast, no browser needed."""
        return await asyncio.to_thread(self._offline_check_sync)

    def _offline_check_sync(self) -> SessionState:
        profile_path = self._profile_dir / f"{self._platform}_profile"
        cookie_paths = [
            profile_path / "Default" / "Cookies",
            profile_path / "Default" / "Network" / "Cookies",
        ]

        domain, auth_names = _PROVIDER_COOKIE_CONFIG.get(
            self._platform, (self._platform, ["session", "token", "auth"])
        )

        for cookie_file in cookie_paths:
            if not cookie_file.exists() or cookie_file.stat().st_size == 0:
                continue
            try:
                conn = sqlite3.connect(str(cookie_file))
                cursor = conn.cursor()
                now_chrome = int((time.time() + 11644473600) * 1_000_000)

                name_conditions = " OR ".join("name LIKE ?" for _ in auth_names)
                params: list[str | int] = [f"%{domain}%"]
                params.extend(f"{p}%" for p in auth_names)
                params.append(now_chrome)

                cursor.execute(
                    f"SELECT COUNT(*) FROM cookies "
                    f"WHERE host_key LIKE ? AND is_persistent = 1 "
                    f"AND ({name_conditions}) "
                    f"AND (has_expires = 0 OR expires_utc > ?)",
                    params,
                )
                count = cursor.fetchone()[0]
                conn.close()

                if count > 0:
                    return SessionState.AUTHENTICATED
                return SessionState.AUTH_EXPIRED

            except Exception as exc:
                logger.debug("%s: offline cookie check error: %s", self._platform, exc)
                if cookie_file.stat().st_size > 1024:
                    return SessionState.AUTHENTICATED

        return SessionState.UNKNOWN

    # ── Online check (DOM inspection) ─────────────────────

    async def _online_check(self, page: Any) -> SessionState:
        """DOM-based session check via platform-specific strategy."""
        try:
            is_logged_in = await self._online_strategy.check(page)
            if is_logged_in:
                return SessionState.AUTHENTICATED
            return SessionState.LOGIN_REQUIRED
        except Exception as exc:
            logger.debug("%s: online check error: %s", self._platform, exc)
            return SessionState.UNKNOWN
