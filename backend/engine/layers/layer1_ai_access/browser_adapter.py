"""Browser-based AI adapter — uses BrowserEngine for page automation."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Any

from shared.types import AIResponse, AIStatus, ProviderStatus, SubmitOptions
from shared.errors import AILoginRequiredError
from .adapter import AIAdapter
from browser.engine import BrowserEngine, AuthStatus

logger = logging.getLogger(__name__)

CJK_PATTERN = r"[一-鿿぀-ゟ゠-ヿ]"


class BrowserAIAdapter(AIAdapter):
    """Base class for AI adapters that use BrowserEngine.

    Subclasses only need to provide:
    - ai_id, ai_name, url
    - _find_input(page) -> locator
    - _extract_response(page, prompt) -> str
    """

    def __init__(self, engine: BrowserEngine, config: dict):
        self._engine = engine
        self._config = config
        self._status = AIStatus.INITIALIZING
        self._consecutive_failures = 0

    @property
    def ai_id(self) -> str:
        return self._config.get("aiId", "unknown")

    @property
    def ai_name(self) -> str:
        return self._config.get("aiName", "Unknown")

    @property
    def url(self) -> str:
        return self._config.get("url", "")

    def get_status(self) -> ProviderStatus:
        return ProviderStatus(
            ai_id=self.ai_id,
            ai_name=self.ai_name,
            status=self._status,
            last_check_at=time.time(),
            consecutive_failures=self._consecutive_failures,
        )

    async def initialize(self) -> None:
        logger.info("Initializing %s adapter...", self.ai_name)
        self._status = AIStatus.READY
        logger.info("%s adapter ready", self.ai_name)

    async def destroy(self) -> None:
        await self._engine.close_page(self.ai_id)
        self._status = AIStatus.INITIALIZING

    async def send_prompt(self, prompt: str, options: SubmitOptions | None = None) -> AIResponse:
        timeout_ms = options.timeout_ms if options else 120000
        task_id = f"{self.ai_id}_{uuid.uuid4().hex[:8]}"
        start_time = time.time()
        self._status = AIStatus.BUSY

        try:
            result = await self._send_async(prompt, timeout_ms)
            duration = time.time() - start_time
            self._status = AIStatus.READY
            self._consecutive_failures = 0
            return AIResponse(
                success=True, ai_id=self.ai_id, task_id=task_id,
                content=result, model=self.ai_id,
                timestamp=time.time(), duration=duration,
                word_count=self._count_words(result),
            )
        except AILoginRequiredError:
            self._status = AIStatus.LOGIN_REQUIRED
            self._consecutive_failures += 1

            # Try to trigger login window
            try:
                logger.info("%s: triggering login window...", self.ai_name)
                login_success = await self._engine.ensure_logged_in(self.ai_id)
                if login_success:
                    # Retry the request after login
                    logger.info("%s: login successful, retrying...", self.ai_name)
                    self._status = AIStatus.BUSY
                    result = await self._send_async(prompt, timeout_ms)
                    duration = time.time() - start_time
                    self._status = AIStatus.READY
                    self._consecutive_failures = 0
                    return AIResponse(
                        success=True, ai_id=self.ai_id, task_id=task_id,
                        content=result, model=self.ai_id,
                        timestamp=time.time(), duration=duration,
                        word_count=self._count_words(result),
                    )
            except Exception as login_err:
                logger.error("%s: login failed: %s", self.ai_name, login_err)

            return AIResponse(
                success=False, ai_id=self.ai_id, task_id=task_id,
                content="", error_code="LOGIN_REQUIRED",
                error_message=f"{self.ai_name} 需要重新登录",
            )
        except Exception as e:
            self._consecutive_failures += 1
            self._status = AIStatus.READY
            logger.exception("%s send_prompt failed", self.ai_name)
            return AIResponse(
                success=False, ai_id=self.ai_id, task_id=task_id,
                content="", error_code=type(e).__name__, error_message=str(e),
            )

    async def _send_async(self, prompt: str, timeout_ms: int) -> str:
        """Send prompt using BrowserEngine."""
        # Get or create page
        page = await self._engine.get_page(self.ai_id, self.url)
        await page.wait_for_timeout(2000)

        # Check login
        auth = await self._engine.check_auth(self.ai_id)
        if auth in (AuthStatus.NOT_LOGGED_IN, AuthStatus.EXPIRED):
            raise AILoginRequiredError(self.ai_id)

        # Find input
        input_box = await self._find_input(page)
        if input_box is None:
            body = ""
            try:
                body = (await page.locator("body").inner_text(timeout=3000))[:200]
            except Exception:
                pass
            if "登录" in body or "login" in body.lower():
                raise AILoginRequiredError(self.ai_id)
            raise RuntimeError(f"Could not find input box. Body: {body[:100]}")

        # Type and send
        await input_box.click()
        await page.wait_for_timeout(300)
        await input_box.fill(prompt)
        await page.wait_for_timeout(500)
        await page.keyboard.press("Enter")

        # Wait for response
        after_send_wait = self._config.get("timing", {}).get("afterSendWaitMs", 1500)
        await page.wait_for_timeout(after_send_wait)

        # Extract response
        return await self._extract_response(page, prompt, timeout_ms)

    async def _find_input(self, page: Any) -> Any:
        """Find the input element. Override in subclasses for AI-specific selectors."""
        selectors = self._config.get("selectors", {}).get("inputBox", ["textarea"])
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=2000):
                    return el
            except Exception:
                continue
        return None

    async def _extract_response(self, page: Any, prompt: str, timeout_ms: int) -> str:
        """Extract response using body text parsing. Override for AI-specific logic."""
        idle_ms = self._config.get("detection", {}).get("idleTimeoutMs", 3000)
        last_response = ""
        idle_start = None
        deadline = time.time() + timeout_ms / 1000

        while time.time() < deadline:
            body = await page.locator("body").inner_text(timeout=3000)
            body = body.replace("\xa0", " ")
            lines = [l.strip() for l in body.split("\n") if l.strip()]

            # Find the user's prompt
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
        raise TimeoutError(f"{self.ai_name} response timed out")

    def _is_ui_element(self, text: str) -> bool:
        """Check if text is a UI element (not part of AI response). Override for AI-specific."""
        ui_elements = {"DeepThink", "Search", "AI-generated, for reference only", "Instant", "New chat", "Today"}
        return text in ui_elements or text.startswith("New chat") or text.startswith("Today")

    @staticmethod
    def _count_words(text: str) -> int:
        cjk = len(re.findall(CJK_PATTERN, text))
        non_cjk = len(re.sub(CJK_PATTERN, " ", text).split())
        return cjk + non_cjk

    async def stop_generation(self) -> None:
        pass

    async def new_conversation(self) -> None:
        await self._engine.close_page(self.ai_id)
