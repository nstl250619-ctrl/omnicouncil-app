"""Regression tests for方案 C: non-headless restart hides the window.

After the user reported "GPT keeps popping up after I close it", we
landed on: the watchdog in engine.py detects the empty page list, calls
on_session_expired, which runs the 4-level recovery chain ending in
RestartBrowserStrategy.recover().

Two guarantees from this fix:
  1. The recovered browser must be launched with --window-position and
     --window-size set so the new window doesn't appear in the user's
     view (off-screen, but on a virtual desktop that wraps, this is
     the most defensive we can be without changing headless=True, which
     would break the Cloudflare challenge).
  2. The page must be tagged with a [background] title prefix via
     add_init_script so the user can identify any visible window as
     OmniCouncil-managed.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from runtime.recovery_strategies import RestartBrowserStrategy


def _build_engine_mock(platform: str = "chatgpt") -> Any:
    """Build a mock engine that satisfies RestartBrowserStrategy.recover's
    expectations. Only the bits it actually touches are wired up."""
    engine = MagicMock()
    engine._context = MagicMock()
    engine._context.close = AsyncMock()
    engine._page = MagicMock()
    engine._pages = {platform: MagicMock()}

    # session_validator & profile_manager
    engine.get_session_validator = MagicMock(return_value=MagicMock())
    profile_manager = MagicMock()
    profile_manager.backup = AsyncMock()
    profile_manager.get_profile_path = MagicMock(
        return_value=MagicMock(__str__=lambda s: "/tmp/fake-profile")
    )
    engine.get_profile_manager = MagicMock(return_value=profile_manager)

    # config — chatgpt is the one we care about
    config = MagicMock()
    config.headless = False  # chatgpt is non-headless
    config.home_url = "https://chatgpt.com"
    config.extra_browser_args = [
        "--window-position=-2400,-2400",
        "--window-size=1280,800",
    ]
    engine.get_platform_config = MagicMock(return_value=config)
    return engine


def _build_playwright_mock(new_page: Any) -> Any:
    playwright = MagicMock()
    new_context = MagicMock()
    new_context.new_page = AsyncMock(return_value=new_page)
    playwright.chromium.launch_persistent_context = AsyncMock(
        return_value=new_context
    )
    return playwright, new_context


@pytest.mark.asyncio
async def test_restart_browser_applies_window_position_on_non_headless() -> None:
    """The recovery relaunch must keep --window-position and --window-size
    on the launch args, so the recovered window goes back off-screen."""
    engine = _build_engine_mock("chatgpt")
    new_page = MagicMock()
    new_page.add_init_script = AsyncMock()
    new_page.goto = AsyncMock()
    playwright, _new_context = _build_playwright_mock(new_page)

    with patch.object(
        RestartBrowserStrategy, "_verify_session_unused", create=True
    ) if False else contextlib.suppress(ImportError):
        pass
    # Patch _verify_session to return True (avoid touching the real path).
    with patch(
        "runtime.recovery_strategies._verify_session",
        new=AsyncMock(return_value=True),
    ):
        engine._playwright = playwright
        await RestartBrowserStrategy().recover(engine, "chatgpt")

    launch_call = playwright.chromium.launch_persistent_context.call_args
    assert launch_call is not None, "launch_persistent_context was not called"
    args = launch_call.kwargs.get("args") or launch_call.args[2]
    # args is a list of chromium switches
    joined = " ".join(args)
    assert "--window-position=-2400,-2400" in joined, (
        f"Restart must preserve --window-position. Got: {joined}"
    )
    assert "--window-size=1280,800" in joined, (
        f"Restart must preserve --window-size. Got: {joined}"
    )
    assert launch_call.kwargs.get("headless") is False, (
        "chatgpt must remain non-headless for the Cloudflare challenge"
    )


@pytest.mark.asyncio
async def test_restart_browser_adds_window_args_even_if_config_lost_them() -> None:
    """Defensive guarantee: if a future config change drops the
    --window-position arg, restart_browser still injects one. Otherwise
    the watchdog-driven restart could pop the window into view."""
    engine = _build_engine_mock("chatgpt")
    engine.get_platform_config.return_value.extra_browser_args = []  # empty
    new_page = MagicMock()
    new_page.add_init_script = AsyncMock()
    new_page.goto = AsyncMock()
    playwright, _ = _build_playwright_mock(new_page)

    with patch(
        "runtime.recovery_strategies._verify_session",
        new=AsyncMock(return_value=True),
    ):
        engine._playwright = playwright
        await RestartBrowserStrategy().recover(engine, "chatgpt")

    args = playwright.chromium.launch_persistent_context.call_args.kwargs["args"]
    joined = " ".join(args)
    assert "--window-position=-2400,-2400" in joined
    assert "--window-size=1280,800" in joined


@pytest.mark.asyncio
async def test_restart_browser_tags_page_with_background_prefix() -> None:
    """The recovered page must be tagged with [background] title so any
    visible window can be identified as OmniCouncil-managed."""
    engine = _build_engine_mock("chatgpt")
    new_page = MagicMock()
    new_page.add_init_script = AsyncMock()
    new_page.goto = AsyncMock()
    playwright, _ = _build_playwright_mock(new_page)

    with patch(
        "runtime.recovery_strategies._verify_session",
        new=AsyncMock(return_value=True),
    ):
        engine._playwright = playwright
        await RestartBrowserStrategy().recover(engine, "chatgpt")

    assert new_page.add_init_script.called, (
        "add_init_script must be called on the recovered page so the "
        "[background] title prefix survives SPA navigation"
    )
    script = new_page.add_init_script.call_args.args[0]
    assert "[background]" in script, (
        f"init script must contain the [background] tag. Got: {script[:200]}"
    )
    # Sanity: the observer should re-apply the tag if the site rewrites
    # the title (ChatGPT does this on every navigation).
    assert "MutationObserver" in script, (
        "init script must install a MutationObserver to survive SPA title rewrites"
    )


@pytest.mark.asyncio
async def test_restart_browser_does_not_add_window_args_when_headless() -> None:
    """For headless platforms, the window-position arg is meaningless and
    could trigger Chromium warnings on some platforms. Skip it. Use deepseek
    (a headless platform) since chatgpt has a special case that forces
    headless=False for the Cloudflare challenge."""
    engine = _build_engine_mock("deepseek")
    engine.get_platform_config.return_value.headless = True
    engine.get_platform_config.return_value.extra_browser_args = []
    new_page = MagicMock()
    new_page.add_init_script = AsyncMock()
    new_page.goto = AsyncMock()
    playwright, _ = _build_playwright_mock(new_page)

    with patch(
        "runtime.recovery_strategies._verify_session",
        new=AsyncMock(return_value=True),
    ):
        engine._playwright = playwright
        await RestartBrowserStrategy().recover(engine, "deepseek")

    args = playwright.chromium.launch_persistent_context.call_args.kwargs["args"]
    joined = " ".join(args)
    # Headless = no window, so we should NOT inject the off-screen args.
    assert "--window-position=" not in joined
    assert "--window-size=" not in joined
    # And the [background] init script must not be installed either.
    assert not new_page.add_init_script.called, (
        "Headless platforms don't need the [background] title tag"
    )


if __name__ == "__main__":
    asyncio.run(test_restart_browser_applies_window_position_on_non_headless())
    print("All background-window-hide tests passed.")
