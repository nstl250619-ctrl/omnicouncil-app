"""Local JSON storage for session history."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class LocalStorage:
    """Local JSON file storage for session history.

    Stores sessions as individual JSON files in ~/.omnicouncil/sessions/.
    """

    def __init__(self, base_dir: str | None = None):
        self._base_dir = Path(base_dir) if base_dir else Path.home() / ".omnicouncil"
        self._sessions_dir = self._base_dir / "sessions"
        self._sessions_dir.mkdir(parents=True, exist_ok=True)

    def save_session(self, session: dict[str, Any]) -> str:
        """Save a session and return its ID."""
        session_id = session.get("task_id", f"session_{int(time.time())}")
        session["saved_at"] = time.time()

        path = self._sessions_dir / f"{session_id}.json"
        path.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Saved session %s", session_id)
        return session_id

    def load_session(self, session_id: str) -> dict[str, Any] | None:
        """Load a session by ID."""
        path = self._sessions_dir / f"{session_id}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error("Failed to load session %s: %s", session_id, e)
            return None

    def list_sessions(self, limit: int = 50) -> list[dict[str, Any]]:
        """List recent sessions, sorted by date descending."""
        sessions = []
        for path in sorted(self._sessions_dir.glob("*.json"), reverse=True)[:limit]:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                # Return summary only
                sessions.append({
                    "task_id": data.get("task_id", path.stem),
                    "query": data.get("query", ""),
                    "ai_ids": data.get("ai_ids", []),
                    "completed_at": data.get("completed_at", 0),
                    "saved_at": data.get("saved_at", 0),
                    "summary": {
                        "total_ais": data.get("summary", {}).get("total_ais", 0),
                        "success_count": data.get("summary", {}).get("success_count", 0),
                        "consensus_count": data.get("consensus_count", 0),
                        "conflict_count": data.get("conflict_count", 0),
                    },
                })
            except Exception as e:
                logger.warning("Failed to read session %s: %s", path.stem, e)
        return sessions

    def delete_session(self, session_id: str) -> bool:
        """Delete a session by ID."""
        path = self._sessions_dir / f"{session_id}.json"
        if path.exists():
            path.unlink()
            logger.info("Deleted session %s", session_id)
            return True
        return False

    def clear_all(self) -> int:
        """Delete all sessions. Returns count of deleted files."""
        count = 0
        for path in self._sessions_dir.glob("*.json"):
            path.unlink()
            count += 1
        logger.info("Cleared %d sessions", count)
        return count
