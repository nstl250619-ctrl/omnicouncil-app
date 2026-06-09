"""Authentication Framework — AuthManager strategy selector."""

from __future__ import annotations

import logging
from typing import Any

from auth.cookie_strategy import CookieAuthStrategy
from auth.oauth_strategy import OAuth2AuthStrategy
from auth.strategy import AuthStrategy
from engine.contracts import AuthConfig, AuthMethod
from shared.types import SessionState

logger = logging.getLogger(__name__)


class AuthManager:
    """认证管理器。

    根据 AuthConfig.method 自动选择对应的 AuthStrategy 实例。
    所有平台特定知识通过 AuthConfig 注入，无硬编码。
    """

    _STRATEGIES: dict[AuthMethod, type[AuthStrategy]] = {
        AuthMethod.COOKIE: CookieAuthStrategy,
        AuthMethod.OAUTH2: OAuth2AuthStrategy,
        # AuthMethod.API_KEY: ApiKeyAuthStrategy,  # Phase 4
    }

    def __init__(self, auth_config: AuthConfig | None) -> None:
        if auth_config is None:
            self._strategy = None
            self._config = None
            return

        self._config = auth_config
        strategy_cls = self._STRATEGIES.get(auth_config.method)
        if strategy_cls is None:
            raise ValueError(
                f"Unknown auth method: {auth_config.method}. "
                f"Available: {list(self._STRATEGIES.keys())}"
            )
        self._strategy = strategy_cls(auth_config)
        logger.info("AuthManager: loaded %s strategy", auth_config.method.value)

    @property
    def strategy(self) -> AuthStrategy | None:
        return self._strategy

    @property
    def method(self) -> AuthMethod | None:
        return self._config.method if self._config else None

    async def detect(self, profile_dir: str, platform: str) -> SessionState:
        """快速检测认证状态。"""
        if self._strategy is None:
            return SessionState.UNKNOWN
        return await self._strategy.detect(profile_dir, platform)

    async def verify(self, page: Any, profile_dir: str, platform: str) -> SessionState:
        """完整验证 Session 有效性。"""
        if self._strategy is None:
            return SessionState.UNKNOWN
        return await self._strategy.verify(page, profile_dir, platform)
