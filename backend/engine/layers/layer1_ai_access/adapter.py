"""AIAdapter base class — interface for individual AI adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod

from shared.types import AIResponse, AIStatus, ProviderStatus, SubmitOptions


class AIAdapter(ABC):
    """Abstract base class for all AI adapters.

    Each AI (DeepSeek, Gemini, etc.) implements this interface.
    The adapter handles: navigation, input, sending, response detection, extraction.
    """

    @property
    @abstractmethod
    def ai_id(self) -> str:
        """Unique identifier for this AI (e.g., 'deepseek')."""
        ...

    @property
    @abstractmethod
    def ai_name(self) -> str:
        """Human-readable name (e.g., 'DeepSeek')."""
        ...

    @property
    @abstractmethod
    def url(self) -> str:
        """AI website URL."""
        ...

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the adapter (e.g., load config, prepare browser)."""
        ...

    @abstractmethod
    async def destroy(self) -> None:
        """Clean up resources (close browser sessions, etc.)."""
        ...

    @abstractmethod
    def get_status(self) -> ProviderStatus:
        """Get current provider status."""
        ...

    @abstractmethod
    async def send_prompt(self, prompt: str, options: SubmitOptions | None = None) -> AIResponse:
        """Send a prompt to the AI and wait for the full response.

        This is the core method. Implementations should:
        1. Navigate to the AI website (or reuse existing session)
        2. Input the prompt
        3. Send it
        4. Wait for the response to complete
        5. Extract and return the response
        """
        ...

    @abstractmethod
    async def stop_generation(self) -> None:
        """Stop ongoing generation (if possible)."""
        ...

    @abstractmethod
    async def new_conversation(self) -> None:
        """Start a new conversation (clear history)."""
        ...

    def is_ready(self) -> bool:
        """Check if this adapter is ready to accept requests."""
        status = self.get_status()
        return status.status == AIStatus.READY
