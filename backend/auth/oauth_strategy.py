"""Authentication Framework — OAuth2AuthStrategy implementation.

Supports OAuth2 token refresh, expiry detection, and manual login guidance.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

from auth.strategy import AuthStrategy
from engine.contracts import AuthConfig, OAuthAuthConfig
from shared.types import SessionState

logger = logging.getLogger(__name__)


class OAuth2AuthStrategy(AuthStrategy):
    """OAuth2 authentication strategy.

    Supports:
    - Token file storage (JSON)
    - Token expiry detection
    - Token refresh via refresh_token
    - Manual login via browser redirect
    """

    def __init__(self, config: AuthConfig) -> None:
        if config.oauth is None:
            raise ValueError("OAuth2AuthStrategy requires AuthConfig.oauth")
        self._oauth_config: OAuthAuthConfig = config.oauth

    async def detect(self, profile_dir: str, platform: str) -> SessionState:
        """Check if OAuth token file exists and is not expired."""
        token_path = Path(profile_dir) / f"{platform}_oauth.json"
        if not token_path.exists():
            return SessionState.UNKNOWN

        try:
            import json
            data = json.loads(token_path.read_text())
            expires_at = data.get("expires_at", 0)
            if expires_at > 0 and time.time() > expires_at:
                return SessionState.AUTH_EXPIRED
            if data.get("access_token"):
                return SessionState.AUTHENTICATED
            return SessionState.UNKNOWN
        except Exception:
            return SessionState.UNKNOWN

    async def verify(self, page: Any, profile_dir: str, platform: str) -> SessionState:
        """Verify OAuth token validity."""
        return await self.detect(profile_dir, platform)

    async def refresh(self, page: Any) -> bool:
        """Attempt to refresh OAuth token using refresh_token."""
        # TODO: Implement OAuth2 token refresh
        logger.debug("OAuth2 refresh not yet implemented")
        return False

    async def login(self, browser: Any, config: Any) -> tuple[bool, str]:
        """Open browser for OAuth login flow."""
        # TODO: Implement OAuth2 browser login
        return False, "OAuth2 login not yet implemented"
