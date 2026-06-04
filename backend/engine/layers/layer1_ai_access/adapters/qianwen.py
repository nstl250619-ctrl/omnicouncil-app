"""Qianwen adapter — Playwright async persistent browser."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from pathlib import Path

from shared.types import AIResponse, AIStatus, ProviderStatus, SubmitOptions
from shared.errors import AILoginRequiredError
from ..adapter import AIAdapter

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "config" / "qianwen.json"

CJK_PATTERN = r"[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff]"


class QianwenAdapter(AIAdapter):
    def __init__(self, user_data_dir=None):
        self._config = self._load_config()
        self._user_data_dir = user_data_dir or str(Path(__file__).parent.parent.parent.parent / "data" / "qianwen_session")
        self._status = AIStatus.INITIALIZING
        self._consecutive_failures = 0
        self._browser = None
        self._context = None
        self._page = None

    @property
    def ai_id(self): return "qianwen"
    @property
    def ai_name(self): return "千问"
    @property
    def url(self): return self._config["url"]

    def _load_config(self):
        if not CONFIG_PATH.exists():
            return {"aiId":"qianwen","aiName":"千问","url":"https://tongyi.aliyun.com/qianwen","selectors":{"inputBox":["textarea","[contenteditable]","[role=textbox]"],"sendButton":[]},"detection":{"idleTimeoutMs":3000,"responseMinLength":1},"timing":{"afterSendWaitMs":2000}}
        with open(CONFIG_PATH) as f: return json.load(f)

    def get_status(self):
        return ProviderStatus(ai_id=self.ai_id, ai_name=self.ai_name, status=self._status, last_check_at=time.time(), consecutive_failures=self._consecutive_failures)

    async def initialize(self):
        logger.info("Initializing Qianwen adapter...")
        Path(self._user_data_dir).mkdir(parents=True, exist_ok=True)
        await self._prewarm_browser()
        self._status = AIStatus.READY
        logger.info("Qianwen adapter ready")

    async def _prewarm_browser(self):
        try:
            from patchright.async_api import async_playwright
            logger.info("Qianwen: launching persistent browser...")
            self._browser = await async_playwright().start()
            self._context = await self._browser.chromium.launch_persistent_context(self._user_data_dir, headless=True, args=["--disable-blink-features=AutomationControlled"])
            self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
            await self._page.goto(self._config["url"], wait_until="domcontentloaded", timeout=60000)
            logger.info("Qianwen: browser ready at %s", self._page.url)
        except Exception as e:
            logger.warning("Qianwen: browser pre-warm failed: %s", e)
            self._browser = None

    async def destroy(self):
        if self._context:
            try: await self._context.close()
            except: pass
        if self._browser:
            try: await self._browser.stop()
            except: pass
        self._browser = self._context = self._page = None
        self._status = AIStatus.INITIALIZING

    async def send_prompt(self, prompt, options=None):
        timeout_ms = options.timeout_ms if options else 120000
        task_id = f"qw_{uuid.uuid4().hex[:8]}"
        start_time = time.time()
        self._status = AIStatus.BUSY
        try:
            result = await self._send_async(prompt, timeout_ms)
            duration = time.time() - start_time
            self._status = AIStatus.READY
            self._consecutive_failures = 0
            return AIResponse(success=True, ai_id=self.ai_id, task_id=task_id, content=result, model="qianwen", timestamp=time.time(), duration=duration, word_count=self._count_words(result))
        except AILoginRequiredError:
            self._status = AIStatus.LOGIN_REQUIRED
            self._consecutive_failures += 1
            return AIResponse(success=False, ai_id=self.ai_id, task_id=task_id, content="", error_code="LOGIN_REQUIRED", error_message="千问需要登录")
        except Exception as e:
            self._consecutive_failures += 1
            self._status = AIStatus.READY
            logger.exception("Qianwen send_prompt failed")
            return AIResponse(success=False, ai_id=self.ai_id, task_id=task_id, content="", error_code=type(e).__name__, error_message=str(e))

    @staticmethod
    def _count_words(text):
        cjk = len(re.findall(CJK_PATTERN, text))
        non_cjk = len(re.sub(CJK_PATTERN, " ", text).split())
        return cjk + non_cjk

    async def _send_async(self, prompt, timeout_ms):
        page = self._page
        if page is None: raise RuntimeError("Browser not initialized")
        await page.goto(self._config["url"], wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)
        if "login" in page.url.lower(): raise AILoginRequiredError("qianwen")
        input_box = None
        for sel in self._config["selectors"]["inputBox"]:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=2000): input_box = el; break
            except: continue
        if input_box is None:
            body = (await page.locator("body").inner_text(timeout=3000))[:200]
            if "登录" in body: raise AILoginRequiredError("qianwen")
            raise RuntimeError(f"No input box. Body: {body[:100]}")
        await input_box.click()
        await page.wait_for_timeout(300)
        await input_box.fill(prompt)
        await page.wait_for_timeout(500)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(self._config["timing"].get("afterSendWaitMs", 2000))
        idle_ms = self._config["detection"].get("idleTimeoutMs", 3000)
        last_response = ""
        idle_start = None
        deadline = time.time() + timeout_ms / 1000
        while time.time() < deadline:
            body = await page.locator("body").inner_text(timeout=3000)
            body = body.replace("\xa0", " ")
            lines = [l.strip() for l in body.split("\n") if l.strip()]
            prompt_idx = None
            for i, line in enumerate(lines):
                if prompt in line: prompt_idx = i; break
            if prompt_idx is not None:
                response_lines = []
                for j in range(prompt_idx + 1, len(lines)):
                    c = lines[j]
                    if len(c) < 2: continue
                    response_lines.append(c)
                response_text = "\n".join(response_lines) if response_lines else ""
                if response_text:
                    if response_text != last_response:
                        last_response = response_text
                        idle_start = time.time()
                    elif idle_start and (time.time() - idle_start) * 1000 >= idle_ms:
                        return response_text
            await page.wait_for_timeout(500)
        if last_response: return last_response
        raise TimeoutError("Qianwen response timed out")

    async def stop_generation(self): pass
    async def new_conversation(self):
        if self._page: await self._page.goto(self._config["url"], wait_until="domcontentloaded", timeout=30000)
