"""Provider base class — unified interface for all AI providers."""

from __future__ import annotations

import contextlib
import logging
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from shared.errors import AILoginRequiredError
from shared.types import AIResponse, AIStatus, ProviderStatus, SubmitOptions

from engine.layers.layer1_ai_access.response_normalizer import ResponseNormalizer

if TYPE_CHECKING:
    from browser.engine import BrowserEngine

logger = logging.getLogger(__name__)

_normalizer = ResponseNormalizer()


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
        2. initialize() — prepare resources (browser pages, etc.)
        3. send_prompt(prompt, options) — send and extract response
        4. destroy() — cleanup resources
    """

    def __init__(self, engine: BrowserEngine | None = None) -> None:
        self._engine = engine
        self._status = AIStatus.INITIALIZING
        self._consecutive_failures = 0

    # ========== Properties (required by AIAccessManager) ==========

    @property
    def ai_id(self) -> str:
        """Unique identifier for this AI (e.g., 'deepseek')."""
        return self.config().provider_id

    @property
    def ai_name(self) -> str:
        """Human-readable name (e.g., 'DeepSeek')."""
        return self.config().display_name

    # ========== Abstract: Configuration ==========

    @abstractmethod
    def config(self) -> ProviderConfig:
        """Return this provider's configuration."""
        ...

    # ========== Runtime: Lifecycle ==========

    async def initialize(self) -> None:
        """Initialize the provider. Override for custom setup."""
        self._status = AIStatus.READY
        logger.info("%s provider ready", self.config().display_name)

    async def destroy(self) -> None:
        """Cleanup resources. Override for custom teardown."""
        if self._engine:
            await self._engine.close_page(self.config().provider_id)
        self._status = AIStatus.INITIALIZING

    # ========== Runtime: Core execution ==========

    async def send_prompt(self, prompt: str, options: SubmitOptions | None = None) -> AIResponse:
        """Send a prompt and wait for the full response.

        This is the single entry point for AI calls.
        Handles: login check → input → send → wait → extract.
        """
        timeout_ms = options.timeout_ms if options else 120000
        task_id = f"{self.config().provider_id}_{uuid.uuid4().hex[:8]}"
        start_time = time.time()
        self._status = AIStatus.BUSY

        try:
            result = await self._send_async(prompt, timeout_ms)
            duration = time.time() - start_time
            self._status = AIStatus.READY
            self._consecutive_failures = 0
            return AIResponse(
                success=True,
                ai_id=self.config().provider_id,
                task_id=task_id,
                content=result,
                model=self.config().provider_id,
                timestamp=time.time(),
                duration=duration,
                word_count=_normalizer.count_words(result),
            )
        except AILoginRequiredError:
            self._status = AIStatus.LOGIN_REQUIRED
            self._consecutive_failures += 1

            # Try to trigger login
            if self._engine:
                try:
                    logger.info("%s: triggering login...", self.config().display_name)
                    login_success = await self._engine.ensure_logged_in(self.config().provider_id)
                    if login_success:
                        self._status = AIStatus.BUSY
                        result = await self._send_async(prompt, timeout_ms)
                        duration = time.time() - start_time
                        self._status = AIStatus.READY
                        self._consecutive_failures = 0
                        return AIResponse(
                            success=True,
                            ai_id=self.config().provider_id,
                            task_id=task_id,
                            content=result,
                            model=self.config().provider_id,
                            timestamp=time.time(),
                            duration=duration,
                            word_count=_normalizer.count_words(result),
                        )
                except Exception as login_err:
                    logger.error("%s: login failed: %s", self.config().display_name, login_err)

            return AIResponse(
                success=False,
                ai_id=self.config().provider_id,
                task_id=task_id,
                content="",
                error_code="LOGIN_REQUIRED",
                error_message=f"{self.config().display_name} 需要重新登录",
            )
        except Exception as e:
            self._consecutive_failures += 1
            self._status = AIStatus.READY
            logger.exception("%s send_prompt failed", self.config().display_name)
            return AIResponse(
                success=False,
                ai_id=self.config().provider_id,
                task_id=task_id,
                content="",
                error_code=type(e).__name__,
                error_message=str(e),
            )

    async def stop_generation(self) -> None:
        """Stop ongoing generation. Override for AI-specific behavior."""
        pass

    async def new_conversation(self) -> None:
        """Start a new conversation. Override for AI-specific behavior."""
        if self._engine:
            await self._engine.close_page(self.config().provider_id)

    # ========== Runtime: Browser automation (default impl) ==========

    async def _send_async(self, prompt: str, timeout_ms: int) -> str:
        """Send prompt via browser automation. Override for AI-specific logic."""
        if not self._engine:
            raise RuntimeError(f"{self.config().display_name}: no browser engine")

        cfg = self.config()
        page = await self._engine.get_page(cfg.provider_id, cfg.chat_url)
        await page.wait_for_timeout(2000)

        # Check login
        from browser.engine import AuthStatus
        auth = await self._engine.check_auth(cfg.provider_id)
        if auth in (AuthStatus.NOT_LOGGED_IN, AuthStatus.EXPIRED):
            raise AILoginRequiredError(cfg.provider_id)

        # Find input
        input_box = await self._find_input(page)
        if input_box is None:
            body = ""
            with contextlib.suppress(Exception):
                body = (await page.locator("body").inner_text(timeout=3000))[:200]
            if "登录" in body or "login" in body.lower():
                raise AILoginRequiredError(cfg.provider_id)
            raise RuntimeError(f"{cfg.display_name}: could not find input box. Body: {body[:100]}")

        # Type and send
        await input_box.click()
        await page.wait_for_timeout(300)
        await input_box.fill(prompt)
        await page.wait_for_timeout(500)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(1500)

        # Extract response
        return await self._extract_response(page, prompt, timeout_ms)

    async def _find_input(self, page: Any) -> Any:
        """Find the input element. Override for AI-specific selectors."""
        for sel in ["textarea", "[contenteditable='true']", "[role='textbox']"]:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=2000):
                    return el
            except Exception:
                continue
        return None

    async def _extract_response(self, page: Any, prompt: str, timeout_ms: int) -> str:
        """Extract response from page. Override for AI-specific parsing."""
        idle_ms = 3000
        last_response = ""
        idle_start = None
        deadline = time.time() + timeout_ms / 1000

        while time.time() < deadline:
            body = await page.locator("body").inner_text(timeout=3000)
            body = body.replace("\xa0", " ")
            lines = [line.strip() for line in body.split("\n") if line.strip()]

            prompt_idx = None
            for i, line in enumerate(lines):
                if prompt in line:
                    prompt_idx = i
                    break

            if prompt_idx is not None:
                response_lines = []
                for j in range(prompt_idx + 1, len(lines)):
                    candidate = lines[j]
                    if self._is_ui_element(candidate):
                        continue
                    response_lines.append(candidate)
                response_text = "\n".join(response_lines) if response_lines else ""

                if response_text:
                    if response_text != last_response:
                        last_response = response_text
                        idle_start = time.time()
                    elif idle_start and (time.time() - idle_start) * 1000 >= idle_ms:
                        return response_text

            await page.wait_for_timeout(500)

        if last_response:
            return last_response
        raise TimeoutError(f"{self.config().display_name} response timed out")

    def _is_ui_element(self, text: str) -> bool:
        """Check if text is a UI element. Override for AI-specific elements."""
        return len(text) < 2

    # ========== Status ==========

    def get_status(self) -> ProviderStatus:
        """Get current provider status."""
        return ProviderStatus(
            ai_id=self.config().provider_id,
            ai_name=self.config().display_name,
            status=self._status,
            last_check_at=time.time(),
            consecutive_failures=self._consecutive_failures,
        )

    def is_ready(self) -> bool:
        """Check if this provider is ready to accept requests."""
        return self._status == AIStatus.READY

    # ========== Legacy: Login check (for WS endpoints) ==========

    async def check_login(self, page: Any) -> bool:
        """Check if the user is logged in on this page. Override for AI-specific logic."""
        return True

    # ========== Utility ==========

    @staticmethod
    def count_words(text: str) -> int:
        """Count words. Delegates to ResponseNormalizer for consistency."""
        return _normalizer.count_words(text)
