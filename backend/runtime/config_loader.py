"""PlatformConfigLoader — load platform configs from YAML files.

Falls back to hardcoded configs if YAML not found.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from engine.contracts import (
    AuthConfig,
    AuthMethod,
    CookieAuthConfig,
    OAuthAuthConfig,
    PageInteractionConfig,
    PlatformCapability,
    PlatformConfig,
)

logger = logging.getLogger(__name__)


class PlatformConfigLoader:
    """Load platform configurations from YAML files.

    Usage:
        loader = PlatformConfigLoader(Path("providers"))
        configs = loader.load_all()
        deepseek_config = configs.get("deepseek")
    """

    def __init__(self, providers_dir: Path) -> None:
        self._providers_dir = providers_dir

    def load_all(self) -> dict[str, PlatformConfig]:
        """Load all platform configs from YAML files."""
        configs: dict[str, PlatformConfig] = {}

        if not self._providers_dir.exists():
            logger.warning("Providers directory not found: %s", self._providers_dir)
            return configs

        for yaml_file in self._providers_dir.glob("*/provider.yaml"):
            try:
                config = self._load_one(yaml_file)
                if config:
                    configs[config.name] = config
                    logger.info("Loaded config for %s from %s", config.name, yaml_file)
            except Exception as e:
                logger.error("Failed to load %s: %s", yaml_file, e)

        return configs

    def _load_one(self, yaml_path: Path) -> PlatformConfig | None:
        """Load a single platform config from YAML."""
        data = yaml.safe_load(yaml_path.read_text())
        if not data:
            return None

        # Parse auth config
        auth = None
        if "auth" in data:
            auth_data = data["auth"]
            method = AuthMethod(auth_data.get("method", "cookie"))
            cookie = None
            oauth = None

            if "cookie" in auth_data:
                c = auth_data["cookie"]
                cookie = CookieAuthConfig(
                    domains=c.get("domains", []),
                    names=c.get("names", []),
                    match=c.get("match", "prefix"),
                )

            if "oauth" in auth_data:
                o = auth_data["oauth"]
                oauth = OAuthAuthConfig(
                    token_url=o.get("token_url", ""),
                    client_id=o.get("client_id", ""),
                    redirect_uri=o.get("redirect_uri", ""),
                    scopes=o.get("scopes", []),
                )

            auth = AuthConfig(method=method, cookie=cookie, oauth=oauth)

        # Parse page interaction config
        page = None
        if "page" in data:
            p = data["page"]
            page = PageInteractionConfig(
                input_selectors=p.get("input_selectors", []),
                response_selectors=p.get("response_selectors", []),
                stop_button_selectors=p.get("stop_button_selectors", []),
                ui_elements=p.get("ui_elements", []),
                login_url_patterns=p.get("login_url_patterns", []),
                cloudflare_check=p.get("cloudflare_check", False),
            )

        # Parse capabilities
        capabilities = None
        if "capabilities" in data:
            c = data["capabilities"]
            capabilities = PlatformCapability(
                supports_streaming=c.get("supports_streaming", True),
                supports_file_upload=c.get("supports_file_upload", False),
                supports_image=c.get("supports_image", False),
                max_input_chars=c.get("max_input_chars", 10000),
                response_format=c.get("response_format", "markdown"),
                requires_chat_mode=c.get("requires_chat_mode", False),
            )

        return PlatformConfig(
            name=data.get("id", ""),
            home_url=data.get("home_url", ""),
            headless=data.get("headless", True),
            heartbeat_interval_s=data.get("heartbeat_interval_s", 60),
            max_recovery_attempts=data.get("max_recovery_attempts", 3),
            recovery_cooldown_s=data.get("recovery_cooldown_s", 30),
            session_check_mode=data.get("session_check_mode", "offline_then_online"),
            auth=auth,
            page=page,
            capabilities=capabilities,
        )
