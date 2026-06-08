"""Targeted regression test for the Qianwen body-extraction fix.

The original bug: `_try_body_extraction` used forward search for the prompt,
which matched the sidebar's "Recent chats" copy of the prompt and returned
the lines that followed it (sidebar chrome / unrelated content) instead of
the AI's actual reply. This caused the first request to appear empty and
trigger a retry.

Fix: switched to reverse search so the LAST occurrence of the prompt is used
(the one in the main conversation area).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from providers.qianwen.query_adapter import QianwenQueryAdapter


class _FakeLocator:
    def __init__(self, text: str) -> None:
        self._text = text

    async def inner_text(self, timeout: int = 3000) -> str:  # noqa: ARG002
        return self._text


def _build_page(body_text: str) -> SimpleNamespace:
    return SimpleNamespace(
        locator=lambda *a, **kw: _FakeLocator(body_text),  # type: ignore[arg-type]
        is_closed=lambda: False,
        url="https://www.qianwen.com/qianwen",
    )


# Body that mimics the qianwen page: sidebar with a recent copy of the
# prompt appears BEFORE the main conversation area, where the prompt
# actually lives.
PROMPT = "深圳宝安区的免费景点"
SIDEBAR_THEN_MAIN_BODY = f"""
qianwen 首页
登录
最近对话
{PROMPT}
昨天 20:13
新对话
{PROMPT}
以下是深圳宝安区值得一去的免费景点推荐:
1. 凤凰山国家矿山公园
2. 海上田园旅游区
3. 立新湖公园
4. 铁岗水库
5. 宝安公园
"""


@pytest.mark.asyncio
async def test_qianwen_body_extraction_uses_reverse_search() -> None:
    """The fix must read the lines AFTER the LAST occurrence of the prompt
    (the main conversation), not the FIRST occurrence (the sidebar)."""
    adapter = QianwenQueryAdapter.__new__(QianwenQueryAdapter)
    # Bypass __init__ since the real one would need a real provider client.
    page = _build_page(SIDEBAR_THEN_MAIN_BODY)

    response = await adapter._try_body_extraction(page, PROMPT)

    assert "凤凰山国家矿山公园" in response, (
        f"Expected the real recommendation list, got: {response!r}"
    )
    assert "海上田园旅游区" in response
    assert "宝安公园" in response


@pytest.mark.asyncio
async def test_qianwen_body_extraction_picks_last_prompt_when_duplicated() -> None:
    """Two identical prompts in the body. The conversation reply lives
    after the SECOND one — that's what we want to extract. The text between
    the two prompts (sidebar chrome) must NOT appear in the response."""
    body = "\n".join(
        [
            "头部 logo",
            f"侧边栏: {PROMPT}",
            "侧边栏: footer-ish text",
            f"主对话: {PROMPT}",
            "AI 真实回答第一行",
            "AI 真实回答第二行",
            "页面底部: 版权",
        ]
    )
    adapter = QianwenQueryAdapter.__new__(QianwenQueryAdapter)
    page = _build_page(body)

    response = await adapter._try_body_extraction(page, PROMPT)

    assert "AI 真实回答第一行" in response, response
    assert "AI 真实回答第二行" in response, response
    # The text between the two prompts (sidebar chrome) must NOT be returned.
    assert "footer-ish text" not in response, (
        f"Reverse search must not return text that appears BEFORE the last "
        f"prompt occurrence. Got: {response!r}"
    )
    # The header logo (above the first prompt) must NOT be returned either.
    assert "头部 logo" not in response, response


@pytest.mark.asyncio
async def test_qianwen_body_extraction_handles_missing_prompt() -> None:
    """If the prompt is nowhere in the body, return empty string cleanly."""
    body = "some other content\nno prompt here\nat all"
    adapter = QianwenQueryAdapter.__new__(QianwenQueryAdapter)
    page = _build_page(body)

    response = await adapter._try_body_extraction(page, "does not appear")

    assert response == ""


if __name__ == "__main__":
    asyncio.run(test_qianwen_body_extraction_uses_reverse_search())
    print("All Qianwen body-extraction tests passed.")
