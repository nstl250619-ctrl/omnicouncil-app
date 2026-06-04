"""Provider base class — unified interface for all AI providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProviderConfig:
    """Configuration for a single AI provider."""
    provider_id: str
    display_name: str
    login_url: str
    chat_url: str
    enabled: bool = True
    icon_color: str = "#6C5CE7"
    icon_emoji: str = "🤖"
    max_concurrent: int = 1
    timeout_ms: int = 120000
    extra: dict = field(default_factory=dict)


class BaseProvider(ABC):
    """Base class for all AI providers.

    Each AI (DeepSeek, Qianwen, Gemini, etc.) implements this class.
    Adding a new AI = create a new directory + implement this class.

    Lifecycle:
        1. config() — return provider configuration
        2. check_login(page) — detect login status
        3. send_message(page, message) — send and extract response
    """

    @abstractmethod
    def config(self) -> ProviderConfig:
        """Return this provider's configuration."""
        ...

    @abstractmethod
    async def check_login(self, page: Any) -> bool:
        """Check if the user is logged in on this page.

        Returns True if logged in, False otherwise.
        Called during login flow and session validation.
        """
        ...

    @abstractmethod
    async def send_message(self, page: Any, message: str) -> str:
        """Send a message and return the AI's response.

        Handles:
        1. Finding the input box
        2. Typing the message
        3. Sending (Enter or click button)
        4. Waiting for response completion
        5. Extracting response text
        """
        ...

    async def on_login_start(self, page: Any) -> None:
        """Hook: called before navigating to login page."""
        pass

    async def on_login_success(self, page: Any) -> None:
        """Hook: called after successful login."""
        pass

    async def on_session_expired(self, page: Any) -> bool:
        """Check if session has expired. Returns True if expired."""
        return False

    def get_input_selector(self) -> str:
        """CSS selector for the message input box."""
        return "textarea"

    def get_submit_selector(self) -> str | None:
        """CSS selector for send button. None = use Enter key."""
        return None
