"""Gemini adapter — Scrapling-based browser automation."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path

from shared.types import AIResponse, AIStatus, ProviderStatus, SubmitOptions
from shared.errors import AILoginRequiredError
from ..adapter import AIAdapter

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "config" / "gemini.json"


class GeminiAdapter(AIAdapter):
    """Gemini adapter using Scrapling StealthyFetcher."""

    def __init__(self, user_data_dir: str | None = None) -> None:
        self._config = self._load_config()
        self._user_data_dir = user_data_dir or str(
            Path(__file__).parent.parent.parent.parent / "data" / "gemini_session"
        )
        self._status = AIStatus.INITIALIZING
        self._consecutive_failures = 0

    @property
    def ai_id(self) -> str:
        return "gemini"

    @property
    def ai_name(self) -> str:
        return "Gemini"

    @property
    def url(self) -> str:
        return self._config["url"]

    def _load_config(self) -> dict:
        if not CONFIG_PATH.exists():
            logger.warning("Gemini config not found at %s, using defaults", CONFIG_PATH)
            return {
                "aiId": "gemini", "aiName": "Gemini", "url": "https://gemini.google.com/app",
                "selectors": {"inputBox": ["div[contenteditable='true']", "textarea"], "sendButton": [], "responseContainer": [], "responseContent": []},
                "detection": {"idleTimeoutMs": 3000, "responseMinLength": 1},
                "timing": {"afterSendWaitMs": 2000},
            }
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    def get_status(self) -> ProviderStatus:
        return ProviderStatus(ai_id=self.ai_id, ai_name=self.ai_name, status=self._status,
                              last_check_at=time.time(), consecutive_failures=self._consecutive_failures)

    async def initialize(self) -> None:
        logger.info("Initializing Gemini adapter...")
        Path(self._user_data_dir).mkdir(parents=True, exist_ok=True)
        self._status = AIStatus.READY
        logger.info("Gemini adapter ready (session: %s)", self._user_data_dir)

    async def destroy(self) -> None:
        self._status = AIStatus.INITIALIZING

    async def send_prompt(self, prompt: str, options: SubmitOptions | None = None) -> AIResponse:
        timeout_ms = options.timeout_ms if options else 120000
        task_id = f"gem_{uuid.uuid4().hex[:8]}"
        start_time = time.time()

        self._status = AIStatus.BUSY

        try:
            result = await asyncio.to_thread(self._fetch_with_scrapling, prompt, timeout_ms)
            duration = time.time() - start_time
            self._status = AIStatus.READY
            self._consecutive_failures = 0

            return AIResponse(success=True, ai_id=self.ai_id, task_id=task_id, content=result,
                              model="gemini", timestamp=time.time(), duration=duration,
                              word_count=self._count_words(result))

        except AILoginRequiredError:
            self._status = AIStatus.LOGIN_REQUIRED
            self._consecutive_failures += 1
            return AIResponse(success=False, ai_id=self.ai_id, task_id=task_id, content="",
                              error_code="LOGIN_REQUIRED", error_message="Gemini login required. Run: python scripts/login_gemini.py")
        except Exception as e:
            self._consecutive_failures += 1
            self._status = AIStatus.READY
            logger.exception("Gemini send_prompt failed")
            return AIResponse(success=False, ai_id=self.ai_id, task_id=task_id, content="",
                              error_code=type(e).__name__, error_message=str(e))

    @staticmethod
    def _count_words(text: str) -> int:
        import re
        cjk = len(re.findall(r"[一-鿿぀-ゟ゠-ヿ]", text))
        non_cjk = len(re.sub(r"[一-鿿぀-ゟ゠-ヿ]", " ", text).split())
        return cjk + non_cjk

    def _find_element(self, page, selectors: list[str], timeout: int = 5000):
        for selector in selectors:
            try:
                page.wait_for_selector(selector, timeout=min(timeout, 2000))
                el = page.locator(selector).first
                if el.is_visible():
                    return el
            except Exception:
                continue
        return None

    def _fetch_with_scrapling(self, prompt: str, timeout_ms: int) -> str:
        from scrapling.fetchers import StealthyFetcher

        config = self._config
        selectors = config["selectors"]
        timing = config["timing"]
        detection = config["detection"]
        captured: dict[str, str | Exception] = {}

        def page_action(page):
            page.wait_for_timeout(5000)

            # Check login
            current_url = page.url
            if "accounts.google.com" in current_url or "signin" in current_url.lower():
                raise AILoginRequiredError("gemini")

            # Find input
            input_box = self._find_element(page, selectors["inputBox"], timeout=10000)
            if input_box is None:
                body_text = ""
                try:
                    body_text = page.locator("body").inner_text(timeout=3000)[:200]
                except Exception:
                    pass
                if "sign in" in body_text.lower() or "login" in body_text.lower():
                    raise AILoginRequiredError("gemini")
                raise RuntimeError(f"Could not find input box. Page text: {body_text[:100]}")

            # Input prompt
            try:
                input_box.click()
                page.wait_for_timeout(300)
                input_box.fill(prompt)
            except Exception:
                try:
                    input_box.click()
                    page.wait_for_timeout(300)
                    input_box.type(prompt, delay=30)
                except Exception as e:
                    raise RuntimeError(f"Failed to input text: {e}")

            page.wait_for_timeout(500)

            # Send
            sent = False
            try:
                page.keyboard.press("Enter")
                sent = True
            except Exception:
                pass

            if not sent:
                send_btn = self._find_element(page, selectors["sendButton"], timeout=2000)
                if send_btn:
                    try:
                        send_btn.click()
                        sent = True
                    except Exception:
                        pass

            if not sent:
                raise RuntimeError("Failed to send message")

            # Wait for response using body text parsing
            page.wait_for_timeout(timing.get("afterSendWaitMs", 2000))

            idle_ms = detection.get("idleTimeoutMs", 3000)
            last_response = ""
            idle_start = None
            deadline = time.time() + timeout_ms / 1000
            ui_skip = {"New chat", "Gemini", "Flash", "Sign in", "Google Terms", "Privacy Policy"}

            while time.time() < deadline:
                try:
                    body = page.locator("body").inner_text(timeout=3000)
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
                            if candidate in ui_skip:
                                continue
                            if any(skip in candidate for skip in ["Google Terms", "Privacy Policy", "EN-US"]):
                                break
                            response_lines.append(candidate)
                        response_text = "\n".join(response_lines) if response_lines else ""

                        if response_text:
                            if response_text != last_response:
                                last_response = response_text
                                idle_start = time.time()
                            elif idle_start and (time.time() - idle_start) * 1000 >= idle_ms:
                                captured["result"] = response_text
                                return
                except Exception:
                    pass

                page.wait_for_timeout(500)

            if last_response:
                captured["result"] = last_response
                return
            captured["error"] = TimeoutError("Gemini response timed out")

        try:
            from scrapling.fetchers import StealthySession
            with StealthySession(headless=True, user_data_dir=self._user_data_dir) as session:
                session.fetch(
                    config["url"], page_action=page_action,
                    network_idle=True, timeout=timeout_ms + 10000,
                )
        except AILoginRequiredError:
            raise
        except Exception as e:
            if "result" not in captured:
                raise

        if "error" in captured:
            raise captured["error"]
        if "result" in captured:
            return captured["result"]
        raise RuntimeError("No response captured from Gemini")

    async def stop_generation(self) -> None:
        logger.info("Gemini stop_generation called (not yet implemented)")

    async def new_conversation(self) -> None:
        logger.info("Gemini new_conversation called (not yet implemented)")
