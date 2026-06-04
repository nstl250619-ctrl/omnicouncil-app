"""Base class for AI adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AIConfig:
    """Configuration for a single AI."""
    ai_id: str
    display_name: str
    login_url: str
    chat_url: str
    enabled: bool = True
    icon_color: str = "#6C5CE7"
    extra: dict = field(default_factory=dict)


class AIAdapter(ABC):
    """Base class for AI adapters.

    Each AI (DeepSeek, Qianwen, Gemini, etc.) implements this class
    to provide its own login detection, input selectors, and response extraction.
    """

    @abstractmethod
    def config(self) -> AIConfig:
        """Return this AI's configuration."""
        ...

    @abstractmethod
    async def check_login(self, page: Any) -> bool:
        """Check if the user is logged in on this page.

        Returns True if logged in, False otherwise.
        This is called during the login flow to detect when login is complete.
        """
        ...

    @abstractmethod
    async def send_message(self, page: Any, message: str) -> str:
        """Send a message and return the AI's response.

        This is the core method that handles:
        1. Finding the input box
        2. Typing the message
        3. Sending (Enter or click button)
        4. Waiting for response
        5. Extracting response text
        """
        ...

    async def on_login_start(self, page: Any) -> None:
        """Hook called before navigating to login page (optional)."""
        pass

    async def on_login_success(self, page: Any) -> None:
        """Hook called after successful login (optional)."""
        pass

    async def on_session_expired(self, page: Any) -> bool:
        """Check if the session has expired. Returns True if expired."""
        return False

    def get_input_selector(self) -> str:
        """CSS selector for the message input box."""
        return "textarea"

    def get_submit_selector(self) -> str | None:
        """CSS selector for the send button. None = use Enter key."""
        return None

    def get_response_selector(self) -> str | None:
        """CSS selector for the AI's response content."""
        return None
