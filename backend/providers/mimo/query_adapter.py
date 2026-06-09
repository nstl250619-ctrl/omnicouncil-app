"""MiMo query adapter — send/wait/extract for xiaomimimo.com.

Defensive refactor:
- Hard-fail on error states (no silent fallback)
- Copy-button Markdown extraction as primary
- JS-based DOM extraction as fallback
- Task ID injection for cross-session pollution prevention
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from providers.base.query_adapter import BaseQueryAdapter, QueryAdapterConfig

logger = logging.getLogger(__name__)


class MiMoQueryAdapter(BaseQueryAdapter):

    def config(self) -> QueryAdapterConfig:
        return QueryAdapterConfig(
            platform="mimo",
            display_name="MiMo",
            home_url="https://aistudio.xiaomimimo.com/#/",
            icon_color="#FF6900",
            icon_emoji="🟠",
        )

    # ── Send ────────────────────────────────────────────────

    async def send_prompt(self, page: Any, prompt: str) -> None:
        """MiMo-specific send with chat mode activation and task ID injection."""
        # Inject task ID for cross-session pollution detection
        task_id = uuid.uuid4().hex[:8]
        await page.evaluate(f"""() => {{
            window.__MIMO_TASK_ID = '{task_id}';
            window.__MIMO_PROMPT_TIME = Date.now();
        }}""")

        # Activate chat mode (hard-fail on error)
        await self._activate_chat_mode(page)

        # Send prompt via base class
        await super().send_prompt(page, prompt)

    # ── Chat mode activation ────────────────────────────────

    async def _activate_chat_mode(self, page: Any) -> None:
        """Ensure MiMo Chat mode is active.

        Raises RuntimeError if chat mode cannot be activated.
        """
        # Check if already on chat page
        url = page.url
        if "/chat" in url.lower():
            logger.debug("MiMo: already on chat page")
            return

        mimo_chat_labels = ["MiMo Chat", "mimo chat", "MIMO Chat", "聊天", "对话"]
        for label in mimo_chat_labels:
            try:
                btn = page.locator(
                    f"button:has-text('{label}'), a:has-text('{label}'), "
                    f"[class*='tab']:has-text('{label}'), [role='tab']:has-text('{label}')"
                ).first
                if await btn.is_visible(timeout=1000):
                    logger.info("MiMo: clicking '%s' to activate chat mode", label)
                    await btn.click()
                    await page.wait_for_timeout(2000)

                    # Verify chat mode is active
                    new_url = page.url
                    if "/chat" in new_url.lower() or await self._has_chat_input(page):
                        logger.info("MiMo: chat mode activated")
                        return
            except Exception:
                continue

        # Chat mode activation failed — hard fail
        raise RuntimeError(
            "MiMo chat mode activation failed: no 'MiMo Chat' button found "
            f"and current URL is {page.url}"
        )

    async def _has_chat_input(self, page: Any) -> bool:
        """Check if page has a visible chat input textarea."""
        try:
            textarea = page.locator("textarea").first
            if await textarea.is_visible(timeout=1000):
                placeholder = await textarea.get_attribute("placeholder") or ""
                return "sign in" not in placeholder.lower()
        except Exception:
            pass
        return False

    # ── Input element detection ──────────────────────────────

    async def _find_input(self, page: Any) -> Any:
        """Locate the chat input element."""
        selectors = [
            "[contenteditable='true'][role='textbox']",
            "[contenteditable='true']",
            "div[contenteditable='true']",
            "textarea",
            "[role='textbox']",
            "main textarea",
            "main [contenteditable='true']",
        ]
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=2000):
                    return el
            except Exception:
                continue
        return None

    # ── Pre-flight check ────────────────────────────────────

    async def pre_flight_check(self, page: Any) -> tuple[bool, str]:
        """Hard pre-flight check: page alive, chat mode, login state."""
        if page.is_closed():
            return False, "page_closed"

        # Check login state via textarea placeholder
        try:
            textarea = page.locator("textarea").first
            if await textarea.is_visible(timeout=1000):
                placeholder = await textarea.get_attribute("placeholder") or ""
                if "sign in" in placeholder.lower():
                    return False, "login_required"
        except Exception:
            pass

        # Check URL for login redirects
        url = page.url
        if any(kw in url.lower() for kw in ["login", "signin", "sign-in", "auth0"]):
            return False, "login_required"

        return True, "ok"

    # ── Response extraction ──────────────────────────────────

    async def _extract_response(self, page: Any, prompt: str, timeout_ms: int) -> str:
        """Extract response with idle-detection loop.

        Strategy:
        1. Wait for content stability (idle for 3s)
        2. Try copy-button Markdown extraction (primary)
        3. Try JS-based DOM extraction (fallback)
        4. If all fail, raise TimeoutError
        """
        idle_ms = 3000
        last_content = ""
        idle_start = None
        deadline = time.time() + timeout_ms / 1000

        while time.time() < deadline:
            # Check stop button — if visible, still generating
            stop_btn = await self._find_stop_button(page)
            if stop_btn is not None:
                try:
                    if await stop_btn.is_visible(timeout=500):
                        idle_start = None
                        await page.wait_for_timeout(500)
                        continue
                except Exception:
                    pass

            # Quick content check for stability
            current = await self._get_latest_response_text(page)
            if current and current != last_content:
                last_content = current
                idle_start = time.time()
            elif current and idle_start and (time.time() - idle_start) * 1000 >= idle_ms:
                # Content stable — extract full response
                return await self._extract_final_response(page, prompt)

            await page.wait_for_timeout(500)

        # Timeout — try one last extraction
        result = await self._extract_final_response(page, prompt)
        if result:
            return result
        raise TimeoutError("MiMo response extraction failed: no content detected")

    async def _extract_final_response(self, page: Any, prompt: str) -> str:
        """Extract the final response after content stabilization.

        Tries copy-button first, then JS extraction.
        Raises TimeoutError if both fail.
        """
        # Primary: copy-button Markdown
        markdown = await self._try_copy_markdown(page)
        if markdown and len(markdown.strip()) > 0:
            # Validate: content should not be the landing page footer
            if not self._is_footer_text(markdown):
                logger.debug("MiMo: extracted via copy button (%d chars)", len(markdown))
                return markdown

        # Fallback: JS-based DOM extraction
        js_content = await self._try_js_extraction(page, prompt)
        if js_content and len(js_content.strip()) > 0:
            if not self._is_footer_text(js_content):
                logger.debug("MiMo: extracted via JS (%d chars)", len(js_content))
                return js_content

        raise TimeoutError("MiMo response extraction failed: no valid content found")

    # ── Copy-button Markdown extraction (primary) ───────────

    async def _try_copy_markdown(self, page: Any) -> str | None:
        """Get response as Markdown by clicking the copy button.

        Intercepts clipboard.writeText to capture the Markdown content.
        Returns Markdown string if successful, None otherwise.
        """
        # Inject clipboard interceptor
        await page.evaluate("""() => {
            window.__copiedMarkdown = null;
            const originalWrite = navigator.clipboard.writeText;
            navigator.clipboard.writeText = (text) => {
                window.__copiedMarkdown = text;
                return originalWrite.call(navigator.clipboard, text);
            };
        }""")

        # Try to find and click the copy button
        copy_selectors = [
            'button[aria-label="Copy"]',
            'button[aria-label="复制"]',
            'button[aria-label="Copy response"]',
            'button[aria-label="Copy to clipboard"]',
            'button:has(svg[class*="copy"])',
            'button:has-text("Copy")',
            'button:has-text("复制")',
        ]

        for sel in copy_selectors:
            try:
                btn = page.locator(sel).last  # Last = most recent response
                if await btn.is_visible(timeout=500):
                    await btn.click()
                    await page.wait_for_timeout(500)

                    # Read intercepted content
                    markdown = await page.evaluate("() => window.__copiedMarkdown")
                    if markdown and len(markdown.strip()) > 0:
                        return markdown.strip()
            except Exception:
                continue

        return None

    # ── JS-based DOM extraction (fallback) ──────────────────

    async def _try_js_extraction(self, page: Any, prompt: str) -> str | None:
        """Extract response via JS DOM traversal.

        Strategy:
        1. Find chat container (ancestor of textarea)
        2. Locate last AI response element
        3. Extract innerHTML
        """
        js_code = """() => {
            // Strategy 1: Find last message/response element
            const selectors = [
                '[class*="message"]:not([class*="input"])',
                '[class*="chat-bubble"]',
                '[class*="response"]',
                '[class*="assistant"]',
                '[class*="bot"]',
                '[data-role="assistant"]',
            ];

            for (const sel of selectors) {
                const els = document.querySelectorAll(sel);
                if (els.length > 0) {
                    const last = els[els.length - 1];
                    const text = last.innerText || last.textContent || '';
                    if (text.trim().length > 10) {
                        return text.trim();
                    }
                }
            }

            // Strategy 2: Find textarea, then get next sibling content
            const textarea = document.querySelector('textarea');
            if (textarea) {
                const container = textarea.closest('[class*="chat"]')
                    || textarea.closest('[class*="conversation"]')
                    || textarea.closest('main')
                    || textarea.parentElement?.parentElement;
                if (container) {
                    const messages = container.querySelectorAll(
                        '[class*="message"], [class*="bubble"], [class*="response"]'
                    );
                    if (messages.length > 0) {
                        const last = messages[messages.length - 1];
                        const text = last.innerText || last.textContent || '';
                        if (text.trim().length > 10) {
                            return text.trim();
                        }
                    }
                }
            }

            return null;
        }"""

        try:
            result = await page.evaluate(js_code)
            if result and isinstance(result, str) and len(result.strip()) > 0:
                return result.strip()
        except Exception as exc:
            logger.debug("MiMo: JS extraction failed: %s", exc)

        return None

    # ── Footer detection ────────────────────────────────────

    def _is_footer_text(self, text: str) -> bool:
        """Check if text is the MiMo landing page footer/disclaimer."""
        footer_patterns = [
            "Developer demo platform",
            "Not a formal AI assistant",
            "AI-generated content only",
            "Citation sources",
        ]
        # If text contains multiple footer patterns, it's likely the footer
        matches = sum(1 for p in footer_patterns if p in text)
        return matches >= 2

    # ── UI element filter (for selector extraction) ──────────

    def _is_ui_element(self, text: str) -> bool:
        ui_elements = {
            "MiMo", "New chat", "Settings", "Sign in", "Send", "Copy",
            "Regenerate", "Help", "History",
        }
        if self._is_footer_text(text):
            return True
        return text in ui_elements or len(text) < 2

    # ── Task ID validation ──────────────────────────────────

    async def _validate_task_id(self, page: Any) -> bool:
        """Check if the task ID injected at send_prompt is still present.

        Returns False if the page was refreshed or navigated away.
        """
        try:
            task_id = await page.evaluate("() => window.__MIMO_TASK_ID")
            return task_id is not None and len(task_id) == 8
        except Exception:
            return False
