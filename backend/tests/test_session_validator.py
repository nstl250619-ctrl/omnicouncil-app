"""Tests for SessionValidator — offline Cookie probe + online DOM check.

Uses tmp_path for real SQLite databases and mock objects for Playwright pages.

Covers:
    - Offline check: authenticated / expired / empty / missing / wrong domain
    - Online check: URL-based / DOM-based / Cloudflare / login redirect
    - Mode: offline / online / offline_then_online
    - Platform strategies: default / qianwen / chatgpt
"""

from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path  # noqa: TC003
from unittest.mock import AsyncMock, MagicMock

from runtime.session_validator import (
    ChatGPTOnlineCheck,
    DefaultOnlineCheck,
    QianwenOnlineCheck,
    SessionValidator,
)
from shared.types import SessionState

# ============================================================
#  Helpers
# ============================================================


def _create_cookie_db(path: Path, domain: str, cookie_name: str, expired: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cookies (
            host_key TEXT, name TEXT, path TEXT,
            expires_utc INTEGER, is_persistent INTEGER DEFAULT 1,
            is_httponly INTEGER DEFAULT 0, has_expires INTEGER DEFAULT 1
        )
    """)
    now_chrome = int((time.time() + 11644473600) * 1_000_000)
    expires = now_chrome - 1_000_000_000 if expired else now_chrome + 86_400 * 365 * 1_000_000
    conn.execute(
        "INSERT INTO cookies (host_key, name, path, expires_utc, is_persistent, has_expires) "
        "VALUES (?, ?, '/', ?, 1, 1)",
        (domain, cookie_name, expires),
    )
    conn.commit()
    conn.close()


def _mock_page(url: str = "https://chat.deepseek.com", title: str = "Chat", visible_input: bool = True) -> MagicMock:
    """Create a mock Playwright Page."""
    page = MagicMock()
    page.url = url
    page.is_closed.return_value = False
    page.title = AsyncMock(return_value=title)

    if visible_input:
        input_el = MagicMock()
        input_el.is_visible = AsyncMock(return_value=True)
        locator = MagicMock()
        locator.first = input_el
        locator.count = AsyncMock(return_value=1)
        locator.nth.return_value = input_el
    else:
        locator = MagicMock()
        locator.first = MagicMock(is_visible=AsyncMock(return_value=False))
        locator.count = AsyncMock(return_value=0)

    page.locator.return_value = locator
    return page


# ============================================================
#  1. Offline check
# ============================================================


class TestOfflineCheck:

    def test_authenticated(self, tmp_path: Path):
        _create_cookie_db(
            tmp_path / "deepseek_profile" / "Default" / "Cookies",
            "chat.deepseek.com", "sessionid",
        )
        sv = SessionValidator(tmp_path, "deepseek", mode="offline")
        assert asyncio.run(sv.validate_offline()) == SessionState.AUTHENTICATED

    def test_expired(self, tmp_path: Path):
        _create_cookie_db(
            tmp_path / "deepseek_profile" / "Default" / "Cookies",
            "chat.deepseek.com", "sessionid", expired=True,
        )
        sv = SessionValidator(tmp_path, "deepseek", mode="offline")
        assert asyncio.run(sv.validate_offline()) == SessionState.AUTH_EXPIRED

    def test_no_cookies(self, tmp_path: Path):
        (tmp_path / "deepseek_profile" / "Default").mkdir(parents=True)
        sv = SessionValidator(tmp_path, "deepseek", mode="offline")
        assert asyncio.run(sv.validate_offline()) == SessionState.UNKNOWN

    def test_missing_profile(self, tmp_path: Path):
        sv = SessionValidator(tmp_path, "deepseek", mode="offline")
        assert asyncio.run(sv.validate_offline()) == SessionState.UNKNOWN

    def test_network_cookies_path(self, tmp_path: Path):
        _create_cookie_db(
            tmp_path / "deepseek_profile" / "Default" / "Network" / "Cookies",
            "chat.deepseek.com", "sessionid",
        )
        sv = SessionValidator(tmp_path, "deepseek", mode="offline")
        assert asyncio.run(sv.validate_offline()) == SessionState.AUTHENTICATED

    def test_chatgpt_cookies(self, tmp_path: Path):
        _create_cookie_db(
            tmp_path / "chatgpt_profile" / "Default" / "Cookies",
            "chatgpt.com", "__Secure-next-auth.session-token",
        )
        sv = SessionValidator(tmp_path, "chatgpt", mode="offline")
        assert asyncio.run(sv.validate_offline()) == SessionState.AUTHENTICATED


# ============================================================
#  2. Online check — DefaultOnlineCheck
# ============================================================


class TestDefaultOnlineCheck:

    def test_logged_in(self):
        page = _mock_page("https://chat.deepseek.com", "DeepSeek")
        strategy = DefaultOnlineCheck("deepseek")
        assert asyncio.run(strategy.check(page)) is True

    def test_login_url(self):
        page = _mock_page("https://chat.deepseek.com/sign_in", "Sign In")
        strategy = DefaultOnlineCheck("deepseek")
        assert asyncio.run(strategy.check(page)) is False

    def test_cloudflare(self):
        page = _mock_page("https://chat.deepseek.com", "Just a moment...")
        strategy = DefaultOnlineCheck("deepseek")
        assert asyncio.run(strategy.check(page)) is False

    def test_no_input(self):
        page = _mock_page("https://chat.deepseek.com", "DeepSeek", visible_input=False)
        strategy = DefaultOnlineCheck("deepseek")
        assert asyncio.run(strategy.check(page)) is False


# ============================================================
#  3. Online check — QianwenOnlineCheck
# ============================================================


class TestQianwenOnlineCheck:

    def test_logged_in_no_login_button(self):
        page = _mock_page("https://www.qianwen.com/qianwen", "千问")
        page.locator.return_value.count = AsyncMock(return_value=0)
        strategy = QianwenOnlineCheck()
        assert asyncio.run(strategy.check(page)) is True

    def test_login_button_visible(self):
        page = MagicMock()
        page.url = "https://www.qianwen.com/qianwen"
        btn = MagicMock()
        btn.is_visible = AsyncMock(return_value=True)
        btn.inner_text = AsyncMock(return_value="登录")
        locator = MagicMock()
        locator.count = AsyncMock(return_value=1)
        locator.nth.return_value = btn
        page.locator.return_value = locator
        strategy = QianwenOnlineCheck()
        assert asyncio.run(strategy.check(page)) is False

    def test_login_url(self):
        page = _mock_page("https://login.qianwen.com", "登录")
        strategy = QianwenOnlineCheck()
        assert asyncio.run(strategy.check(page)) is False


# ============================================================
#  4. Online check — ChatGPTOnlineCheck
# ============================================================


class TestChatGPTOnlineCheck:

    def test_logged_in(self):
        page = _mock_page("https://chatgpt.com", "ChatGPT")
        strategy = ChatGPTOnlineCheck()
        assert asyncio.run(strategy.check(page)) is True

    def test_auth_login_redirect(self):
        page = _mock_page("https://auth0.openai.com/login", "Login")
        strategy = ChatGPTOnlineCheck()
        assert asyncio.run(strategy.check(page)) is False

    def test_cloudflare(self):
        page = _mock_page("https://chatgpt.com", "Just a moment")
        strategy = ChatGPTOnlineCheck()
        assert asyncio.run(strategy.check(page)) is False


# ============================================================
#  5. SessionValidator.validate() — mode routing
# ============================================================


class TestValidateMode:

    def test_offline_only(self, tmp_path: Path):
        _create_cookie_db(
            tmp_path / "deepseek_profile" / "Default" / "Cookies",
            "chat.deepseek.com", "sessionid",
        )
        sv = SessionValidator(tmp_path, "deepseek", mode="offline")
        result = asyncio.run(sv.validate(page=_mock_page()))
        assert result == SessionState.AUTHENTICATED

    def test_online_only(self, tmp_path: Path):
        sv = SessionValidator(tmp_path, "deepseek", mode="online")
        page = _mock_page("https://chat.deepseek.com")
        result = asyncio.run(sv.validate(page=page))
        assert result == SessionState.AUTHENTICATED

    def test_online_no_page_returns_unknown(self, tmp_path: Path):
        sv = SessionValidator(tmp_path, "deepseek", mode="online")
        result = asyncio.run(sv.validate(page=None))
        assert result == SessionState.UNKNOWN

    def test_offline_then_online_offline_succeeds(self, tmp_path: Path):
        _create_cookie_db(
            tmp_path / "deepseek_profile" / "Default" / "Cookies",
            "chat.deepseek.com", "sessionid",
        )
        sv = SessionValidator(tmp_path, "deepseek", mode="offline_then_online")
        result = asyncio.run(sv.validate(page=_mock_page()))
        assert result == SessionState.AUTHENTICATED

    def test_offline_then_online_offline_fails_online_succeeds(self, tmp_path: Path):
        sv = SessionValidator(tmp_path, "deepseek", mode="offline_then_online")
        page = _mock_page("https://chat.deepseek.com")
        result = asyncio.run(sv.validate(page=page))
        assert result == SessionState.AUTHENTICATED

    def test_offline_then_online_both_fail(self, tmp_path: Path):
        sv = SessionValidator(tmp_path, "deepseek", mode="offline_then_online")
        page = _mock_page("https://chat.deepseek.com/sign_in")
        result = asyncio.run(sv.validate(page=page))
        assert result == SessionState.LOGIN_REQUIRED


# ============================================================
#  6. validate_online() direct
# ============================================================


class TestValidateOnline:

    def test_authenticated(self, tmp_path: Path):
        sv = SessionValidator(tmp_path, "deepseek")
        page = _mock_page("https://chat.deepseek.com")
        assert asyncio.run(sv.validate_online(page)) == SessionState.AUTHENTICATED

    def test_login_required(self, tmp_path: Path):
        sv = SessionValidator(tmp_path, "deepseek")
        page = _mock_page("https://chat.deepseek.com/sign_in", visible_input=False)
        assert asyncio.run(sv.validate_online(page)) == SessionState.LOGIN_REQUIRED

    def test_page_exception_returns_unknown(self, tmp_path: Path):
        sv = SessionValidator(tmp_path, "deepseek")
        page = MagicMock()
        page.url = property(lambda self: (_ for _ in ()).throw(RuntimeError("crash")))
        # The strategy catches exceptions and returns False → LOGIN_REQUIRED
        assert asyncio.run(sv.validate_online(page)) == SessionState.LOGIN_REQUIRED
