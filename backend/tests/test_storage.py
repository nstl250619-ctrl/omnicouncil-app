"""Unit tests for storage/local.py."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from storage.local import LocalStorage


class TestLocalStorage:
    def setup_method(self):
        self.storage = LocalStorage(base_dir="/tmp/omnicouncil_test_storage")
        # Clean up
        import shutil
        p = Path("/tmp/omnicouncil_test_storage/sessions")
        if p.exists():
            shutil.rmtree(p)
        p.mkdir(parents=True, exist_ok=True)

    def test_save_session(self):
        session = {"task_id": "t1", "query": "test", "ai_ids": ["deepseek"]}
        sid = self.storage.save_session(session)
        assert sid == "t1"

    def test_load_session(self):
        session = {"task_id": "t2", "query": "test"}
        self.storage.save_session(session)
        loaded = self.storage.load_session("t2")
        assert loaded is not None
        assert loaded["task_id"] == "t2"
        assert "saved_at" in loaded

    def test_load_nonexistent(self):
        result = self.storage.load_session("nonexistent")
        assert result is None

    def test_list_sessions(self):
        self.storage.save_session({"task_id": "a", "query": "q1"})
        self.storage.save_session({"task_id": "b", "query": "q2"})
        sessions = self.storage.list_sessions()
        assert len(sessions) >= 2

    def test_delete_session(self):
        self.storage.save_session({"task_id": "t3"})
        assert self.storage.delete_session("t3") is True
        assert self.storage.load_session("t3") is None

    def test_delete_nonexistent(self):
        assert self.storage.delete_session("nonexistent") is False

    def test_clear_all(self):
        self.storage.save_session({"task_id": "x"})
        self.storage.save_session({"task_id": "y"})
        count = self.storage.clear_all()
        assert count >= 2
        assert len(self.storage.list_sessions()) == 0
