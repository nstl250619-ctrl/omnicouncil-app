"""Session storage — manages login state persistence."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SessionStorage:
    """Manages session data persistence for AI providers.

    Stores login state, cookies, and profile information.
    """

    def __init__(self, base_dir: str | None = None):
        self._base_dir = Path(base_dir) if base_dir else Path.home() / ".omnicouncil"
        self._auth_dir = self._base_dir / "auth"
        self._auth_dir.mkdir(parents=True, exist_ok=True)

    def get_profile_dir(self, provider_id: str) -> str:
        """Get the persistent profile directory for a provider."""
        profile_dir = self._auth_dir / f"{provider_id}_profile"
        profile_dir.mkdir(parents=True, exist_ok=True)
        return str(profile_dir)

    def get_auth_path(self, provider_id: str) -> Path:
        """Get the auth state file path for a provider."""
        return self._auth_dir / f"{provider_id}.json"

    def has_session(self, provider_id: str) -> bool:
        """Check if a saved session exists for a provider."""
        profile_dir = self._auth_dir / f"{provider_id}_profile"
        return profile_dir.exists() and any(profile_dir.iterdir())

    def save_session(self, provider_id: str, data: dict[str, Any]) -> bool:
        """Save session data to file."""
        try:
            path = self.get_auth_path(provider_id)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
            logger.info("Saved session for %s", provider_id)
            return True
        except Exception as e:
            logger.error("Failed to save session for %s: %s", provider_id, e)
            return False

    def load_session(self, provider_id: str) -> dict[str, Any] | None:
        """Load session data from file."""
        path = self.get_auth_path(provider_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except Exception as e:
            logger.error("Failed to load session for %s: %s", provider_id, e)
            return None

    def delete_session(self, provider_id: str) -> bool:
        """Delete session data for a provider."""
        import shutil
        profile_dir = self._auth_dir / f"{provider_id}_profile"
        auth_file = self.get_auth_path(provider_id)

        deleted = False
        if profile_dir.exists():
            shutil.rmtree(profile_dir)
            deleted = True
        if auth_file.exists():
            auth_file.unlink()
            deleted = True

        if deleted:
            logger.info("Deleted session for %s", provider_id)
        return deleted
