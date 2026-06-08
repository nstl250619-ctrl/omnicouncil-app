"""Recovery strategies — individual steps in the recovery chain.

Each strategy implements the ``RecoveryStrategy`` protocol from
``engine.contracts``.  They are executed in order by ``RecoveryEngine``.

Strategy chain (escalating severity):
    1. ``ReloadStrategy``       — page.reload()                          (15s)
    2. ``RenavigateStrategy``   — page.goto(home_url)                    (20s)
    3. ``NewTabStrategy``       — context.new_page() → goto → close old  (20s)
    4. ``RestartBrowserStrategy`` — close context → re-launch             (30s)

All strategies:
    - Operate on the engine's cached Page (via ``engine.get_page()`` or
      internal access).
    - Validate success via ``SessionValidator.validate_online()``.
    - Return True on success, False on failure (never raise).
    - Respect their ``timeout_s`` via ``asyncio.wait_for``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from runtime.session_validator import SessionValidator

logger = logging.getLogger(__name__)


# ============================================================
#  Helper: safe session validation after recovery action
# ============================================================


async def _verify_session(
    session_validator: SessionValidator,
    page: Any,
    platform: str,
) -> bool:
    """Check if session is valid after a recovery action.

    Uses online check (DOM-based) since we just navigated/reloaded.
    Returns True if AUTHENTICATED.
    """
    try:
        from shared.types import SessionState

        state = await session_validator.validate_online(page)
        return state == SessionState.AUTHENTICATED
    except Exception as exc:
        logger.debug("%s: post-recovery verify failed: %s", platform, exc)
        return False


# ============================================================
#  1. ReloadStrategy
# ============================================================


class ReloadStrategy:
    """Level 1: Reload the current page.

    Fastest recovery — just refreshes the page.  Works when the
    session cookie is still valid but the page state is stale.
    """

    name: str = "reload"
    timeout_s: int = 15

    async def recover(self, engine: Any, platform: str) -> bool:
        """Reload the page and verify session.

        Args:
            engine: Runtime engine with ``get_page()`` and
                    ``get_session_validator()``.
            platform: Platform identifier.

        Returns:
            True if session is valid after reload.
        """
        try:
            page = engine.get_page()
            if page is None or page.is_closed():
                return False

            session_validator = engine.get_session_validator()

            await asyncio.wait_for(
                page.reload(wait_until="domcontentloaded"),
                timeout=self.timeout_s - 2,
            )
            await page.wait_for_timeout(2000)

            return await _verify_session(session_validator, page, platform)

        except TimeoutError:
            logger.warning("%s: reload timed out", platform)
            return False
        except Exception as exc:
            logger.debug("%s: reload failed: %s", platform, exc)
            return False


# ============================================================
#  2. RenavigateStrategy
# ============================================================


class RenavigateStrategy:
    """Level 2: Navigate to the platform's home URL.

    Slightly more aggressive than reload — forces a fresh navigation
    which may trigger re-auth via existing cookies.
    """

    name: str = "renavigate"
    timeout_s: int = 20

    async def recover(self, engine: Any, platform: str) -> bool:
        """Navigate to home URL and verify session.

        Args:
            engine: Runtime engine with ``get_page()``,
                    ``get_session_validator()``, and
                    ``get_platform_config()``.
            platform: Platform identifier.

        Returns:
            True if session is valid after navigation.
        """
        try:
            page = engine.get_page()
            if page is None or page.is_closed():
                return False

            session_validator = engine.get_session_validator()
            config = engine.get_platform_config()
            home_url = config.home_url

            await asyncio.wait_for(
                page.goto(home_url, wait_until="domcontentloaded"),
                timeout=self.timeout_s - 3,
            )
            await page.wait_for_timeout(3000)

            return await _verify_session(session_validator, page, platform)

        except TimeoutError:
            logger.warning("%s: renavigate timed out", platform)
            return False
        except Exception as exc:
            logger.debug("%s: renavigate failed: %s", platform, exc)
            return False


# ============================================================
#  3. NewTabStrategy
# ============================================================


class NewTabStrategy:
    """Level 3: Close the current tab and open a new one.

    Useful when the page is in an unrecoverable state (e.g. crashed
    renderer) but the browser context is still alive.
    """

    name: str = "new_tab"
    timeout_s: int = 20

    async def recover(self, engine: Any, platform: str) -> bool:
        """Open a new tab, navigate, close old tab, verify session.

        Args:
            engine: Runtime engine with ``get_page()``,
                    ``get_session_validator()``,
                    ``get_platform_config()``, and access to the
                    browser context (``engine._context``).
            platform: Platform identifier.

        Returns:
            True if session is valid in the new tab.
        """
        try:
            old_page = engine.get_page()
            session_validator = engine.get_session_validator()
            config = engine.get_platform_config()
            home_url = config.home_url

            # Get browser context
            context = getattr(engine, "_context", None)
            if context is None:
                logger.debug("%s: no browser context for new_tab", platform)
                return False

            # Create new page
            new_page = await asyncio.wait_for(
                context.new_page(),
                timeout=5,
            )

            try:
                await asyncio.wait_for(
                    new_page.goto(home_url, wait_until="domcontentloaded"),
                    timeout=self.timeout_s - 5,
                )
                await new_page.wait_for_timeout(3000)

                success = await _verify_session(
                    session_validator, new_page, platform
                )

                if success:
                    # Swap pages: update engine's cached page
                    if hasattr(engine, "_page"):
                        engine._page = new_page
                    if hasattr(engine, "_pages"):
                        engine._pages[platform] = new_page

                    # Close old page
                    if old_page is not None and not old_page.is_closed():
                        with contextlib.suppress(Exception):
                            await old_page.close()

                    logger.info("%s: new_tab recovery succeeded", platform)
                    return True
                else:
                    # New tab also failed — close it, keep old
                    with contextlib.suppress(Exception):
                        await new_page.close()
                    return False

            except Exception:
                with contextlib.suppress(Exception):
                    await new_page.close()
                raise

        except TimeoutError:
            logger.warning("%s: new_tab timed out", platform)
            return False
        except Exception as exc:
            logger.debug("%s: new_tab failed: %s", platform, exc)
            return False


# ============================================================
#  4. RestartBrowserStrategy
# ============================================================


class RestartBrowserStrategy:
    """Level 4: Close the browser context and re-launch.

    Most aggressive — shuts down the entire browser context and
    starts fresh from the profile.  Uses ``ProfileManager`` to
    ensure the profile is healthy before re-launch.
    """

    name: str = "restart_browser"
    timeout_s: int = 30

    async def recover(self, engine: Any, platform: str) -> bool:
        """Restart browser from profile and verify session.

        Args:
            engine: Runtime engine with ``get_page()``,
                    ``get_session_validator()``,
                    ``get_profile_manager()``,
                    ``get_platform_config()``, and browser
                    lifecycle methods.
            platform: Platform identifier.

        Returns:
            True if session is valid after restart.
        """
        try:
            session_validator = engine.get_session_validator()
            profile_manager = engine.get_profile_manager()
            config = engine.get_platform_config()

            # 1. Backup profile before restart
            try:
                await profile_manager.backup(platform)
                logger.info("%s: profile backed up before restart", platform)
            except Exception as exc:
                logger.warning("%s: pre-restart backup failed: %s", platform, exc)

            # 2. Close existing context
            context = getattr(engine, "_context", None)
            if context is not None:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(
                        context.close(),
                        timeout=5,
                    )
                if hasattr(engine, "_context"):
                    engine._context = None

            # Clear cached page
            if hasattr(engine, "_page"):
                engine._page = None
            if hasattr(engine, "_pages"):
                engine._pages.pop(platform, None)

            # 3. Re-launch browser
            playwright = getattr(engine, "_playwright", None)
            if playwright is None:
                logger.debug("%s: no playwright instance for restart", platform)
                return False

            profile_path = profile_manager.get_profile_path(platform)


            headless = config.headless
            extra_args = list(config.extra_browser_args)

            # ChatGPT special: non-headless for Cloudflare
            if platform == "chatgpt":
                headless = False
                extra_args.extend([
                    "--disable-web-security",
                    "--disable-features=ChromeWhatsNewUI",
                ])

            # Non-headless platforms (currently just chatgpt) get an extra
            # window position + size hint on top of whatever the platform
            # config supplies, so a recovery that re-launches the browser
            # can't bring the window back into the user's view. The values
            # match the initial-launch args in main.py and are deliberately
            # re-applied here so that even if the platform config loses the
            # args, the watchdog-driven restart stays invisible.
            if not headless:
                # Only add if not already present to avoid duplicates.
                if not any(a.startswith("--window-position=") for a in extra_args):
                    extra_args.append("--window-position=-2400,-2400")
                if not any(a.startswith("--window-size=") for a in extra_args):
                    extra_args.append("--window-size=1280,800")

            launch_args = [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-features=IsolateOrigins,site-per-process",
                *extra_args,
            ]

            new_context = await asyncio.wait_for(
                playwright.chromium.launch_persistent_context(
                    str(profile_path),
                    headless=headless,
                    args=launch_args,
                ),
                timeout=15,
            )

            if hasattr(engine, "_context"):
                engine._context = new_context

            # 4. Create page and navigate
            new_page = await new_context.new_page()

            # For non-headless platforms, tag the page with a [background]
            # prefix that survives SPA navigation. The MutationObserver
            # re-applies it whenever the site's own code rewrites document
            # title (e.g. ChatGPT appends conversation names). This way if
            # the window ever does become visible, the user can see at a
            # glance that it's the OmniCouncil-managed Cloudflare browser,
            # not a window they opened themselves.
            if not headless:
                try:
                    await new_page.add_init_script(
                        """
                        (() => {
                            const tag = '[background] ';
                            const apply = () => {
                                try {
                                    if (
                                        document.title &&
                                        !document.title.startsWith(tag)
                                    ) {
                                        document.title = tag + document.title;
                                    }
                                } catch (_) {}
                            };
                            const installObserver = () => {
                                const head = document.head || document.documentElement;
                                if (!head || head.__bgObserved) return;
                                head.__bgObserved = true;
                                const obs = new MutationObserver(apply);
                                obs.observe(head, {
                                    childList: true,
                                    subtree: true,
                                    characterData: true,
                                });
                                apply();
                            };
                            if (document.readyState === 'loading') {
                                document.addEventListener(
                                    'DOMContentLoaded',
                                    installObserver,
                                    { once: true },
                                );
                            } else {
                                installObserver();
                            }
                        })();
                        """
                    )
                except Exception as exc:
                    logger.debug(
                        "%s: failed to install [background] title tag (%s)",
                        platform, exc,
                    )

            await asyncio.wait_for(
                new_page.goto(config.home_url, wait_until="domcontentloaded"),
                timeout=10,
            )
            await new_page.wait_for_timeout(3000)

            if hasattr(engine, "_page"):
                engine._page = new_page
            if hasattr(engine, "_pages"):
                engine._pages[platform] = new_page

            # 5. Verify session
            success = await _verify_session(
                session_validator, new_page, platform
            )

            if success:
                logger.info("%s: restart_browser recovery succeeded", platform)
            else:
                logger.warning("%s: restart_browser — session still invalid", platform)

            return success

        except TimeoutError:
            logger.warning("%s: restart_browser timed out", platform)
            return False
        except Exception as exc:
            logger.debug("%s: restart_browser failed: %s", platform, exc)
            return False


# ============================================================
#  Default strategy chain
# ============================================================


def default_recovery_chain() -> list:
    """Return the default ordered list of recovery strategies."""
    return [
        ReloadStrategy(),
        RenavigateStrategy(),
        NewTabStrategy(),
        RestartBrowserStrategy(),
    ]
