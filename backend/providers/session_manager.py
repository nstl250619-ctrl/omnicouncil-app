"""ProviderSessionManager — DEPRECATED: use runtime components instead.

.. deprecated::
    Superseded by ``runtime.session_validator.SessionValidator`` and
    ``runtime.health_monitor.HealthMonitor``.
"""

from __future__ import annotations
import warnings
warnings.warn(
    "providers.session_manager is deprecated; use runtime.session_validator instead.",
    DeprecationWarning, stacklevel=2,
)

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ProviderSessionManager:
    """Manages provider login sessions with persistence.

    Paths:
      ~/.omnicouncil/auth/{provider_id}/         — Chromium profile (cookies)
      ~/.omnicouncil/auth/{provider_id}.json      — storage_state export
      ~/.omnicouncil/sessions/{provider_id}.json  — session metadata
    """

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self._base_dir = Path(base_dir) if base_dir else Path.home() / ".omnicouncil"
        self._auth_dir = self._base_dir / "auth"
        self._sessions_dir = self._base_dir / "sessions"
        self._auth_dir.mkdir(parents=True, exist_ok=True)
        self._sessions_dir.mkdir(parents=True, exist_ok=True)

    def get_profile_dir(self, provider_id: str) -> str:
        profile = self._auth_dir / f"{provider_id}_profile"
        profile.mkdir(parents=True, exist_ok=True)
        return str(profile)

    def get_storage_state_path(self, provider_id: str) -> Path:
        return self._auth_dir / f"{provider_id}.json"

    def has_session(self, provider_id: str) -> bool:
        """Check if a saved session exists (cookie file present)."""
        profile = self._auth_dir / f"{provider_id}_profile"
        cookie_paths = [
            profile / "Default" / "Cookies",
            profile / "Default" / "Network" / "Cookies",
        ]
        return any(p.exists() and p.stat().st_size > 0 for p in cookie_paths)

    def save_session_meta(self, provider_id: str, data: dict[str, Any]) -> None:
        path = self._sessions_dir / f"{provider_id}.json"
        data["saved_at"] = time.time()
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Saved session meta for %s", provider_id)

    def load_session_meta(self, provider_id: str) -> dict[str, Any] | None:
        path = self._sessions_dir / f"{provider_id}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def invalidate_session(self, provider_id: str) -> None:
        """Delete session data for a provider."""
        import shutil
        profile = self._auth_dir / f"{provider_id}_profile"
        storage = self.get_storage_state_path(provider_id)
        meta = self._sessions_dir / f"{provider_id}.json"

        if profile.exists():
            shutil.rmtree(profile, ignore_errors=True)
        if storage.exists():
            storage.unlink(missing_ok=True)
        if meta.exists():
            meta.unlink(missing_ok=True)
        logger.info("Invalidated session for %s", provider_id)

    def is_session_valid(self, provider_id: str) -> bool:
        """Check if session exists and is not expired."""
        return self.has_session(provider_id)

    def list_sessions(self) -> list[dict[str, Any]]:
        """List all saved sessions."""
        result = []
        for path in sorted(self._sessions_dir.glob("*.json"), reverse=True)[:50]:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                result.append(data)
            except Exception:
                pass
        return result
