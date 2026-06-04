"""BrowserEngine — abstract base class for browser automation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable


class EngineMode(str, Enum):
    CDP = "cdp"
    EMBEDDED = "embedded"


class AuthStatus(str, Enum):
    AUTHENTICATED = "authenticated"
    EXPIRED = "expired"
    NOT_LOGGED_IN = "not_logged_in"
    CAPTCHA_REQUIRED = "captcha_required"
    UNKNOWN = "unknown"


@dataclass
class PageInfo:
    """Information about a browser page."""
    ai_id: str
    url: str
    title: str
    is_logged_in: bool
    auth_status: AuthStatus


@dataclass
class EngineStatus:
    """Status of the browser engine."""
    mode: EngineMode
    connected: bool
    browser_version: str
    active_pages: list[PageInfo]


class BrowserEngine(ABC):
    """Abstract browser engine interface.

    Implementations:
    - CDPEngine: Connects to local Chrome via CDP
    - EmbeddedEngine: Launches embedded Chromium
    """

    @property
    @abstractmethod
    def mode(self) -> EngineMode:
        """Engine mode identifier."""
        ...

    @abstractmethod
    async def connect(self) -> bool:
        """Connect to or launch the browser. Returns True on success."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect and cleanup."""
        ...

    @abstractmethod
    async def is_connected(self) -> bool:
        """Check if browser is connected."""
        ...

    @abstractmethod
    async def get_page(self, ai_id: str, url: str) -> Any:
        """Get or create a page for the given AI.

        Returns a Playwright Page object.
        """
        ...

    @abstractmethod
    async def close_page(self, ai_id: str) -> None:
        """Close a specific AI's page."""
        ...

    @abstractmethod
    async def check_auth(self, ai_id: str) -> AuthStatus:
        """Check if the user is logged in for the given AI."""
        ...

    @abstractmethod
    async def ensure_logged_in(self, ai_id: str, on_login_required: Callable | None = None) -> bool:
        """Ensure login is valid. If expired, trigger re-login flow.

        Returns True if logged in.
        """
        ...

    @abstractmethod
    async def get_status(self) -> EngineStatus:
        """Get current engine status."""
        ...

    @abstractmethod
    async def save_auth_state(self, ai_id: str) -> bool:
        """Save current auth state (cookies, localStorage) for persistence."""
        ...

    @abstractmethod
    async def load_auth_state(self, ai_id: str) -> bool:
        """Load saved auth state."""
        ...
