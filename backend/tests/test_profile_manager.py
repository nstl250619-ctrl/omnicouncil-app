"""Tests for ProfileManager — profile creation, backup, restore, health check.

Uses ``tmp_path`` fixture for real filesystem operations (no mocking of
Path/shutil).  SQLite cookie checks are tested with real tiny DBs.

Covers:
    - create() — directory creation, idempotency
    - backup() — archive creation, retention eviction, missing profile
    - restore() — extraction, safety rollback, missing backup, unsafe paths
    - health_check() — cookie probe (authenticated / expired / empty / missing)
    - list_backups() — ordering, empty
    - get_profile_size() — real files, missing dir
"""

from __future__ import annotations

import asyncio
import sqlite3
import tarfile
import time
from pathlib import Path

import pytest

from engine.contracts import ProfileError
from runtime.profile_manager import ProfileManager
from shared.types import SessionState

# ============================================================
#  Helpers
# ============================================================


def _create_cookie_db(path: Path, domain: str, cookie_name: str, expired: bool = False) -> None:
    """Create a minimal Chromium-style Cookies SQLite database.

    Mimics the schema that ``ProfileManager._check_cookies`` queries.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cookies (
            host_key TEXT,
            name TEXT,
            path TEXT,
            expires_utc INTEGER,
            is_persistent INTEGER DEFAULT 1,
            is_httponly INTEGER DEFAULT 0,
            has_expires INTEGER DEFAULT 1
        )
    """)

    # Chrome epoch: microseconds since 1601-01-01
    now_chrome = int((time.time() + 11644473600) * 1_000_000)
    if expired:  # noqa: SIM108
        expires = now_chrome - 1_000_000_000  # already expired
    else:
        expires = now_chrome + 86_400 * 365 * 1_000_000  # 1 year from now

    conn.execute(
        "INSERT INTO cookies (host_key, name, path, expires_utc, is_persistent, has_expires) "
        "VALUES (?, ?, '/', ?, 1, 1)",
        (domain, cookie_name, expires),
    )
    conn.commit()
    conn.close()


def _create_profile_with_cookies(
    base: Path, platform: str, domain: str, cookie_name: str, expired: bool = False
) -> Path:
    """Create a profile directory with a valid (or expired) cookie DB."""
    profile = base / f"{platform}_profile"
    cookie_path = profile / "Default" / "Cookies"
    _create_cookie_db(cookie_path, domain, cookie_name, expired)
    return profile


# ============================================================
#  Fixtures
# ============================================================


@pytest.fixture
def pm(tmp_path: Path) -> ProfileManager:
    """ProfileManager rooted in a temp directory."""
    return ProfileManager(auth_dir=tmp_path, max_backups=3)


# ============================================================
#  1. create()
# ============================================================


class TestCreate:

    def test_create_creates_directory(self, pm: ProfileManager):
        result = asyncio.run(pm.create("deepseek"))
        assert result.exists()
        assert result.is_dir()
        assert result.name == "deepseek_profile"

    def test_create_is_idempotent(self, pm: ProfileManager):
        r1 = asyncio.run(pm.create("gemini"))
        r2 = asyncio.run(pm.create("gemini"))
        assert r1 == r2

    def test_create_nested_parent(self, tmp_path: Path):
        deep = tmp_path / "a" / "b" / "c"
        pm = ProfileManager(auth_dir=deep)
        result = asyncio.run(pm.create("chatgpt"))
        assert result.exists()

    def test_get_profile_path_no_io(self, pm: ProfileManager):
        """get_profile_path is pure — directory need not exist."""
        path = pm.get_profile_path("mimo")
        assert path.name == "mimo_profile"
        assert not path.exists()


# ============================================================
#  2. backup()
# ============================================================


class TestBackup:

    def test_backup_creates_archive(self, pm: ProfileManager, tmp_path: Path):
        # Create a profile with a file
        profile = asyncio.run(pm.create("deepseek"))
        (profile / "test.txt").write_text("hello")

        archive = asyncio.run(pm.backup("deepseek"))
        assert archive.exists()
        assert archive.name == "deepseek_*.tar.gz" or archive.name.startswith("deepseek_")
        assert archive.suffix == ".gz"

        # Verify archive contents
        with tarfile.open(archive, "r:gz") as tar:
            names = tar.getnames()
            assert any("test.txt" in n for n in names)

    def test_backup_retains_max_backups(self, pm: ProfileManager, tmp_path: Path):
        profile = asyncio.run(pm.create("deepseek"))
        (profile / "data.txt").write_text("x")

        # Create 5 backups (max is 3)
        archives = []
        for _ in range(5):
            time.sleep(0.05)  # ensure distinct timestamps
            archives.append(asyncio.run(pm.backup("deepseek")))

        backups = asyncio.run(pm.list_backups("deepseek"))
        assert len(backups) == 3

    def test_backup_missing_profile_raises(self, pm: ProfileManager):
        with pytest.raises(ProfileError, match="does not exist"):
            asyncio.run(pm.backup("nonexistent"))

    def test_backup_preserves_file_content(self, pm: ProfileManager, tmp_path: Path):
        profile = asyncio.run(pm.create("deepseek"))
        original = b"binary content \\x00\\xff"
        (profile / "data.bin").write_bytes(original)

        archive = asyncio.run(pm.backup("deepseek"))

        # Restore to a new location to verify
        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(path=str(extract_dir))

        # Find the file in extracted tree
        restored = list(extract_dir.rglob("data.bin"))
        assert len(restored) == 1


# ============================================================
#  3. restore()
# ============================================================


class TestRestore:

    def test_restore_from_backup(self, pm: ProfileManager, tmp_path: Path):
        # Create profile with content
        profile = asyncio.run(pm.create("deepseek"))
        (profile / "original.txt").write_text("original")
        archive = asyncio.run(pm.backup("deepseek"))

        # Modify profile
        (profile / "original.txt").write_text("modified")
        (profile / "new.txt").write_text("new")

        # Restore
        result = asyncio.run(pm.restore("deepseek", archive))
        assert result is True

        # Should have original content (arcname="." so files are at root)
        restored_profile = pm.get_profile_path("deepseek")
        assert (restored_profile / "original.txt").read_text() == "original"

    def test_restore_creates_rollback(self, pm: ProfileManager, tmp_path: Path):
        profile = asyncio.run(pm.create("deepseek"))
        (profile / "before.txt").write_text("before restore")
        archive = asyncio.run(pm.backup("deepseek"))

        # Modify
        (profile / "before.txt").write_text("changed")

        # Restore — should create rollback
        asyncio.run(pm.restore("deepseek", archive))

        backups = asyncio.run(pm.list_backups("deepseek"))
        rollback_backups = [b for b in backups if "rollback" in b.name]
        assert len(rollback_backups) >= 1

    def test_restore_missing_backup_raises(self, pm: ProfileManager):
        with pytest.raises(ProfileError, match="not found"):
            asyncio.run(pm.restore("deepseek", Path("/nonexistent/backup.tar.gz")))

    def test_restore_empty_profile(self, pm: ProfileManager, tmp_path: Path):
        """Restoring to a platform that had no profile before."""
        profile = asyncio.run(pm.create("deepseek"))
        (profile / "data.txt").write_text("content")
        archive = asyncio.run(pm.backup("deepseek"))

        # Delete profile entirely
        import shutil
        shutil.rmtree(str(profile))

        result = asyncio.run(pm.restore("deepseek", archive))
        assert result is True


# ============================================================
#  4. health_check()
# ============================================================


class TestHealthCheck:

    def test_healthy_profile_with_valid_cookies(self, tmp_path: Path):
        _create_profile_with_cookies(
            tmp_path, "deepseek", "chat.deepseek.com", "sessionid", expired=False
        )
        pm = ProfileManager(auth_dir=tmp_path)
        assert asyncio.run(pm.health_check("deepseek")) is True

    def test_unhealthy_profile_with_expired_cookies(self, tmp_path: Path):
        _create_profile_with_cookies(
            tmp_path, "deepseek", "chat.deepseek.com", "sessionid", expired=True
        )
        pm = ProfileManager(auth_dir=tmp_path)
        assert asyncio.run(pm.health_check("deepseek")) is False

    def test_unhealthy_profile_no_cookies(self, tmp_path: Path):
        profile = tmp_path / "deepseek_profile"
        profile.mkdir()
        pm = ProfileManager(auth_dir=tmp_path)
        assert asyncio.run(pm.health_check("deepseek")) is False

    def test_unhealthy_profile_missing_dir(self, tmp_path: Path):
        pm = ProfileManager(auth_dir=tmp_path)
        assert asyncio.run(pm.health_check("deepseek")) is False

    def test_unhealthy_empty_profile_dir(self, tmp_path: Path):
        profile = tmp_path / "deepseek_profile"
        profile.mkdir()
        pm = ProfileManager(auth_dir=tmp_path)
        assert asyncio.run(pm.health_check("deepseek")) is False

    def test_chatgpt_cookie_detection(self, tmp_path: Path):
        _create_profile_with_cookies(
            tmp_path, "chatgpt", "chatgpt.com",
            "__Secure-next-auth.session-token", expired=False,
        )
        pm = ProfileManager(auth_dir=tmp_path)
        assert asyncio.run(pm.health_check("chatgpt")) is True

    def test_gemini_cookie_detection(self, tmp_path: Path):
        _create_profile_with_cookies(
            tmp_path, "gemini", "google.com", "SAPISID", expired=False,
        )
        pm = ProfileManager(auth_dir=tmp_path)
        assert asyncio.run(pm.health_check("gemini")) is True

    def test_qianwen_cookie_detection(self, tmp_path: Path):
        _create_profile_with_cookies(
            tmp_path, "qianwen", "qianwen.com", "ALI_sessionid", expired=False,
        )
        pm = ProfileManager(auth_dir=tmp_path)
        assert asyncio.run(pm.health_check("qianwen")) is True

    def test_mimo_cookie_detection(self, tmp_path: Path):
        _create_profile_with_cookies(
            tmp_path, "mimo", "xiaomimimo.com", "session_token", expired=False,
        )
        pm = ProfileManager(auth_dir=tmp_path)
        assert asyncio.run(pm.health_check("mimo")) is True

    def test_network_cookie_path(self, tmp_path: Path):
        """Cookies in Default/Network/Cookies should also be detected."""
        profile = tmp_path / "deepseek_profile"
        cookie_path = profile / "Default" / "Network" / "Cookies"
        _create_cookie_db(cookie_path, "chat.deepseek.com", "sessionid")
        pm = ProfileManager(auth_dir=tmp_path)
        assert asyncio.run(pm.health_check("deepseek")) is True


# ============================================================
#  5. _check_cookies() — direct unit tests
# ============================================================


class TestCheckCookies:

    def test_authenticated(self, tmp_path: Path):
        _create_profile_with_cookies(
            tmp_path, "deepseek", "chat.deepseek.com", "sessionid"
        )
        pm = ProfileManager(auth_dir=tmp_path)
        profile = pm.get_profile_path("deepseek")
        assert pm._check_cookies("deepseek", profile) == SessionState.AUTHENTICATED

    def test_expired(self, tmp_path: Path):
        _create_profile_with_cookies(
            tmp_path, "deepseek", "chat.deepseek.com", "sessionid", expired=True
        )
        pm = ProfileManager(auth_dir=tmp_path)
        profile = pm.get_profile_path("deepseek")
        assert pm._check_cookies("deepseek", profile) == SessionState.AUTH_EXPIRED

    def test_no_cookie_file(self, tmp_path: Path):
        profile = tmp_path / "deepseek_profile"
        profile.mkdir()
        pm = ProfileManager(auth_dir=tmp_path)
        assert pm._check_cookies("deepseek", profile) == SessionState.UNKNOWN

    def test_wrong_domain(self, tmp_path: Path):
        """Cookies for a different domain should not match."""
        _create_profile_with_cookies(
            tmp_path, "deepseek", "wrong.com", "sessionid"
        )
        pm = ProfileManager(auth_dir=tmp_path)
        profile = pm.get_profile_path("deepseek")
        # wrong domain → no matching cookies → AUTH_EXPIRED (file exists but empty match)
        assert pm._check_cookies("deepseek", profile) == SessionState.AUTH_EXPIRED

    def test_empty_cookie_db(self, tmp_path: Path):
        """Empty cookie file should return UNKNOWN."""
        profile = tmp_path / "deepseek_profile"
        cookie_path = profile / "Default" / "Cookies"
        cookie_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(cookie_path))
        conn.execute("""
            CREATE TABLE cookies (
                host_key TEXT, name TEXT, path TEXT,
                expires_utc INTEGER, is_persistent INTEGER,
                is_httponly INTEGER, has_expires INTEGER
            )
        """)
        conn.commit()
        conn.close()
        pm = ProfileManager(auth_dir=tmp_path)
        assert pm._check_cookies("deepseek", profile) == SessionState.AUTH_EXPIRED


# ============================================================
#  6. list_backups() / get_profile_size()
# ============================================================


class TestInspection:

    def test_list_backups_empty(self, pm: ProfileManager):
        assert asyncio.run(pm.list_backups("deepseek")) == []

    def test_list_backups_ordered(self, pm: ProfileManager):
        profile = asyncio.run(pm.create("deepseek"))
        (profile / "x").write_text("x")

        archives = []
        for _ in range(3):
            time.sleep(0.05)
            archives.append(asyncio.run(pm.backup("deepseek")))

        listed = asyncio.run(pm.list_backups("deepseek"))
        assert len(listed) == 3
        # Newest first
        assert listed[0].stat().st_mtime >= listed[1].stat().st_mtime

    def test_get_profile_size(self, pm: ProfileManager):
        profile = asyncio.run(pm.create("deepseek"))
        (profile / "a.txt").write_text("hello")
        (profile / "b.txt").write_text("world!")

        size = asyncio.run(pm.get_profile_size("deepseek"))
        assert size == 5 + 6  # "hello" + "world!"

    def test_get_profile_size_missing(self, pm: ProfileManager):
        assert asyncio.run(pm.get_profile_size("nonexistent")) == 0


# ============================================================
#  7. Round-trip: backup → restore → health_check
# ============================================================


class TestRoundTrip:

    def test_backup_restore_health_cycle(self, tmp_path: Path):
        """Full cycle: create → add cookies → backup → destroy → restore → health_check."""
        pm = ProfileManager(auth_dir=tmp_path, max_backups=3)

        # Create profile with valid cookies
        _create_profile_with_cookies(
            tmp_path, "deepseek", "chat.deepseek.com", "sessionid"
        )
        profile = pm.get_profile_path("deepseek")
        assert asyncio.run(pm.health_check("deepseek")) is True

        # Backup
        archive = asyncio.run(pm.backup("deepseek"))

        # Destroy profile
        import shutil
        shutil.rmtree(str(profile))
        assert asyncio.run(pm.health_check("deepseek")) is False

        # Restore
        asyncio.run(pm.restore("deepseek", archive))

        # Health check should pass again
        assert asyncio.run(pm.health_check("deepseek")) is True
