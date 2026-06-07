"""Qianwen (千问) query adapter — send/wait/extract for qianwen.com."""

from __future__ import annotations

import time
from typing import Any

from providers.base.query_adapter import BaseQueryAdapter, QueryAdapterConfig


class QianwenQueryAdapter(BaseQueryAdapter):

    def config(self) -> QueryAdapterConfig:
        return QueryAdapterConfig(
            platform="qianwen",
            display_name="千问",
            home_url="https://www.qianwen.com/qianwen",
            icon_color="#F59E0B",
            icon_emoji="🟠",
        )

    async def _find_input(self, page: Any) -> Any:
        selectors = [
            "[contenteditable='true'][role='textbox']",
            "[contenteditable='true']",
            "textarea",
        ]
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=2000):
                    return el
            except Exception:
                continue
        return None

    async def pre_flight_check(self, page: Any) -> tuple[bool, str]:
        """千问 DOM-based login check."""
        if page.is_closed():
            return False, "page_closed"
        url = page.url
        if "login" in url.lower() or "signin" in url.lower():
            return False, "login_required"
        # Check for visible login button
        try:
            login_btns = page.locator('button:has-text("登录"), a:has-text("登录")')
            count = await login_btns.count()
            for i in range(count):
                btn = login_btns.nth(i)
                if await btn.is_visible():
                    text = await btn.inner_text()
                    if text.strip() == "登录":
                        return False, "login_required"
        except Exception:
            pass
        return True, "ok"

    def _is_ui_element(self, text: str) -> bool:
        ui_elements = {
            "新建对话", "我的空间", "智能体", "最近对话", "关于千问",
            "Qwen3.7-千问", "Qwen3.7-Max", "Qwen3.7-Turbo", "API 服务", "下载电脑端",
            "你好，我是千问", "向千问提问", "打招呼：你好！",
            "任务助理", "思考", "研究", "千问高考", "PPT创作",
            "更多", "内测", "AI生图", "AI生视频", "代码",
            "翻译", "AI写作", "录音纪要", "HappyHorse",
            "登录", "注册", "用千问APP扫码登录",
            "用户协议", "隐私政策", "帮助中心",
            "内容由AI生成，可能不准确，请注意核实",
            "千问 - 阿里旗下全能AI助手",
        }
        if text in ui_elements:
            return True
        if len(text) < 2:
            return True
        if text.startswith("新建") or text.startswith("关于"):
            return True
        if text.startswith("Qwen") and len(text) < 20:
            return True
        if "AI生成" in text or "不准确" in text:
            return True
        return bool("阿里旗下" in text or "全能AI助手" in text)

    async def _extract_response(self, page: Any, prompt: str, timeout_ms: int) -> str:
        idle_ms = 3000
        last_response = ""
        idle_start = None
        deadline = time.time() + timeout_ms / 1000

        while time.time() < deadline:
            stop_btn = await self._find_stop_button(page)
            if stop_btn is not None:
                try:
                    if await stop_btn.is_visible(timeout=500):
                        idle_start = None
                        await page.wait_for_timeout(500)
                        continue
                except Exception:
                    pass

            response_text = await self._try_selector_extraction(page, prompt)
            if not response_text:
                response_text = await self._try_body_extraction(page, prompt)

            if response_text:
                if response_text != last_response:
                    last_response = response_text
                    idle_start = time.time()
                elif idle_start and (time.time() - idle_start) * 1000 >= idle_ms:
                    return response_text

            await page.wait_for_timeout(500)

        if last_response:
            return last_response
        raise TimeoutError("千问 response timed out")

    async def _try_selector_extraction(self, page: Any, prompt: str) -> str:
        selectors = [
            '[data-role="assistant"]',
            '[class*="assistant"]',
            '[class*="message"][class*="ai"]',
            '[class*="bot-message"]',
            '[class*="response-content"]',
            '[class*="answer-content"]',
            '[class*="markdown-container"]',
        ]
        for sel in selectors:
            try:
                elements = page.locator(sel)
                count = await elements.count()
                if count > 0:
                    last_el = elements.nth(count - 1)
                    text = await last_el.inner_text(timeout=2000)
                    text = text.replace("\xa0", " ").strip()
                    if text and len(text) > 2:
                        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
                        clean_lines = [
                            ln for ln in lines
                            if not self._is_ui_element(ln) and prompt not in ln
                        ]
                        clean_text = "\n".join(clean_lines)
                        if clean_text:
                            return clean_text
            except Exception:
                continue
        return ""

    async def _try_body_extraction(self, page: Any, prompt: str) -> str:
        try:
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
                return "\n".join(response_lines) if response_lines else ""
        except Exception:
            pass
        return ""
