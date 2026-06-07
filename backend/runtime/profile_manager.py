"""ProfileManager — Chrome profile lifecycle management.

Manages profile directories for each AI platform: creation, backup,
restore, and offline health checks.  Fully independent of
``BrowserEngine`` — depends only on file paths and SQLite.

All disk I/O is dispatched via ``asyncio.to_thread`` to avoid
blocking the event loop.

Profile path convention (compatible with existing ``EmbeddedEngine``)::

    ~/.omnicouncil/auth/
        {platform}_profile/
            Default/
                Cookies            ← Chromium cookie DB
                Network/
                    Cookies        ← alternate location
        backups/
            {platform}/
                {platform}_{timestamp}.tar.gz
                {platform}_rollback_{timestamp}.tar.gz

Backups live at the auth level (``backups/{platform}/``), NOT inside the
profile directory, so that ``restore()`` can safely delete the profile
without destroying the backup archive or the rollback snapshot.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import tarfile
import time
from pathlib import Path

from engine.contracts import ProfileError
from engine.contracts import ProfileManager as ProfileManagerABC
from shared.types import SessionState

logger = logging.getLogger(__name__)

# Per-provider cookie domain + auth cookie name patterns.
# Mirrors ``EmbeddedEngine._has_valid_session`` but is path-based.
_PROVIDER_COOKIE_CONFIG: dict[str, tuple[str, list[str]]] = {
    "deepseek": ("chat.deepseek.com", ["sessionid", "token", "auth"]),
    "qianwen":  ("qianwen.com",       ["sid", "login_", "ALI_", "Session", "cookie2"]),
    "gemini":   ("google.com",        ["SAPISID", "SSID", "__Secure-", "OSID"]),
    "chatgpt":  ("chatgpt.com",       [
        "__Secure-next-auth.session-token",
        "__Host-next-auth.csrf-token",
    ]),
    "mimo":     ("xiaomimimo.com",    ["session", "token", "auth"]),
}

_DEFAULT_AUTH_DIR = Path.home() / ".omnicouncil" / "auth"
_MAX_BACKUPS = 3


class ProfileManager(ProfileManagerABC):
    """Concrete ``ProfileManager`` backed by the local filesystem.

    Parameters
    ----------
    auth_dir:
        Root directory for all profiles.  Defaults to
        ``~/.omnicouncil/auth/``.  Each platform gets a subdirectory
        named ``{platform}_profile/``.
    max_backups:
        Number of backup archives to retain per platform.  Older
        archives are automatically deleted.  Default 3.
    """

    def __init__(
        self,
        auth_dir: Path | str | None = None,
        max_backups: int = _MAX_BACKUPS,
    ) -> None:
        self._auth_dir = Path(auth_dir) if auth_dir else _DEFAULT_AUTH_DIR
        self._max_backups = max_backups

    # ── Path helpers ───────────────────────────────────────

    def get_profile_path(self, platform: str) -> Path:
        """Return the profile directory for *platform*.

        Pure path computation — no I/O.
        """
        return self._auth_dir / f"{platform}_profile"

    def _backup_dir(self, platform: str) -> Path:
        """Backup directory at the auth level, outside the profile directory.

        Path: ``{auth_dir}/backups/{platform}/``
        """
        return self._auth_dir / "backups" / platform

    # ── Create ─────────────────────────────────────────────

    async def create(self, platform: str) -> Path:
        """Ensure the profile directory exists and return its path.

        Creates parent directories if needed.  Does NOT launch a browser.

        Raises:
            ProfileError: If directory creation fails.
        """
        profile_path = self.get_profile_path(platform)

        def _create() -> Path:
            try:
                profile_path.mkdir(parents=True, exist_ok=True)
                return profile_path
            except OSError as exc:
                raise ProfileError(platform, f"mkdir failed: {exc}") from exc

        return await asyncio.to_thread(_create)

    # ── Backup ─────────────────────────────────────────────

    async def backup(self, platform: str) -> Path:
        """Snapshot the profile directory into a ``.tar.gz`` archive.

        Archives are stored under ``{profile_dir}/backups/``.
        Older backups beyond ``max_backups`` are automatically deleted.

        Raises:
            ProfileError: If the profile directory does not exist or
                archiving fails.
        """
        profile_path = self.get_profile_path(platform)
        backup_dir = self._backup_dir(platform)

        def _backup() -> Path:
            if not profile_path.exists():
                raise ProfileError(platform, "profile directory does not exist")

            backup_dir.mkdir(parents=True, exist_ok=True)

            timestamp = int(time.time() * 1000)  # millisecond precision
            archive_name = f"{platform}_{timestamp}.tar.gz"
            archive_path = backup_dir / archive_name

            try:
                with tarfile.open(archive_path, "w:gz") as tar:
                    # arcname="." so extraction to profile_path yields
                    # {profile_path}/Default/Cookies, not
                    # {profile_path}/{platform}/Default/Cookies
                    tar.add(str(profile_path), arcname=".")
            except (OSError, tarfile.TarError) as exc:
                # Clean up partial archive
                archive_path.unlink(missing_ok=True)
                raise ProfileError(platform, f"backup failed: {exc}") from exc

            # Evict old backups
            self._evict_old_backups(backup_dir, platform)

            logger.info("Profile backup: %s -> %s", platform, archive_path)
            return archive_path

        return await asyncio.to_thread(_backup)

    def _evict_old_backups(self, backup_dir: Path, platform: str) -> None:
        """Delete backup archives beyond the retention limit."""
        pattern = f"{platform}_*.tar.gz"
        backups = sorted(backup_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
        for old_backup in backups[self._max_backups:]:
            try:
                old_backup.unlink()
                logger.info("Evicted old backup: %s", old_backup)
            except OSError:
                logger.warning("Failed to evict backup: %s", old_backup)

    # ── Restore ────────────────────────────────────────────

    async def restore(self, platform: str, backup_path: Path) -> bool:
        """Restore a profile from a backup archive.

        Before overwriting, the current profile is backed up
        automatically (safety rollback).

        Raises:
            ProfileError: If *backup_path* does not exist or
                extraction fails.
        """
        backup_path = Path(backup_path)
        profile_path = self.get_profile_path(platform)

        def _restore() -> bool:
            if not backup_path.exists():
                raise ProfileError(platform, f"backup not found: {backup_path}")

            # Safety rollback: backup current state before overwriting.
            # Rollup is stored at the auth-level backup dir (outside profile).
            if profile_path.exists():
                try:
                    rollback_path = self._create_rollback(platform, profile_path)
                    logger.info("Rollback snapshot: %s", rollback_path)
                except Exception as exc:
                    logger.warning("Rollback snapshot failed (continuing): %s", exc)

            # Remove current profile
            if profile_path.exists():
                shutil.rmtree(str(profile_path))

            # Extract backup (archive lives outside profile dir, safe to read)
            try:
                with tarfile.open(backup_path, "r:gz") as tar:
                    # Security: reject paths that escape the profile directory
                    for member in tar.getmembers():
                        member_path = (profile_path / member.name).resolve()
                        if not str(member_path).startswith(str(profile_path.resolve())):
                            raise ProfileError(
                                platform,
                                f"unsafe path in archive: {member.name}",
                            )
                    tar.extractall(path=str(profile_path))
            except (OSError, tarfile.TarError) as exc:
                raise ProfileError(platform, f"restore failed: {exc}") from exc

            logger.info("Profile restored: %s from %s", platform, backup_path)
            return True

        return await asyncio.to_thread(_restore)

    def _create_rollback(self, platform: str, profile_path: Path) -> Path:
        """Create a quick rollback snapshot before restore.

        Unlike ``backup()``, this is synchronous and does NOT evict
        old backups — it's a safety net, not a first-class archive.
        """
        backup_dir = self._backup_dir(platform)
        backup_dir.mkdir(parents=True, exist_ok=True)

        timestamp = int(time.time() * 1000)  # millisecond precision
        rollback_name = f"{platform}_rollback_{timestamp}.tar.gz"
        rollback_path = backup_dir / rollback_name

        with tarfile.open(rollback_path, "w:gz") as tar:
            tar.add(str(profile_path), arcname=".")

        return rollback_path

    # ── Health check ───────────────────────────────────────

    async def health_check(self, platform: str) -> bool:
        """Quick offline health check — no browser launched.

        Checks:
            1. Profile directory exists and is non-empty.
            2. Cookie file exists and contains unexpired auth cookies
               for the platform's domain.

        This reuses the SQLite probe logic from
        ``EmbeddedEngine._has_valid_session`` but depends only on
        the file path — no engine instance required.
        """
        profile_path = self.get_profile_path(platform)

        def _check() -> bool:
            if not profile_path.exists():
                return False

            # Check for any files in the profile directory
            try:
                next(profile_path.iterdir())
            except StopIteration:
                return False

            state = self._check_cookies(platform, profile_path)
            return state == SessionState.AUTHENTICATED

        return await asyncio.to_thread(_check)

    def _check_cookies(self, platform: str, profile_path: Path) -> SessionState:
        """Offline Cookie SQLite probe.

        Mirrors ``EmbeddedEngine._has_valid_session`` but is a pure
        function of *profile_path* — no engine dependency.
        """
        cookie_paths = [
            profile_path / "Default" / "Cookies",
            profile_path / "Default" / "Network" / "Cookies",
        ]

        domain, auth_names = _PROVIDER_COOKIE_CONFIG.get(
            platform, (platform, ["session", "token", "auth"])
        )

        for cookie_file in cookie_paths:
            if not cookie_file.exists() or cookie_file.stat().st_size == 0:
                continue
            try:
                import sqlite3

                conn = sqlite3.connect(str(cookie_file))
                cursor = conn.cursor()
                now_chrome = int((time.time() + 11644473600) * 1_000_000)

                name_conditions = " OR ".join("name LIKE ?" for _ in auth_names)
                params: list[str | int] = [f"%{domain}%"]
                params.extend(f"{p}%" for p in auth_names)
                params.append(now_chrome)

                cursor.execute(
                    f"SELECT COUNT(*) FROM cookies "
                    f"WHERE host_key LIKE ? AND is_persistent = 1 "
                    f"AND ({name_conditions}) "
                    f"AND (has_expires = 0 OR expires_utc > ?)",
                    params,
                )
                count = cursor.fetchone()[0]
                conn.close()

                if count > 0:
                    return SessionState.AUTHENTICATED
                return SessionState.AUTH_EXPIRED

            except Exception as exc:
                logger.debug("%s: cookie check error: %s", platform, exc)
                # Fallback: size > 1KB is probably a real cookie store
                if cookie_file.stat().st_size > 1024:
                    return SessionState.AUTHENTICATED

        return SessionState.UNKNOWN

    # ── Listing / inspection ───────────────────────────────

    async def list_backups(self, platform: str) -> list[Path]:
        """Return a list of backup archives for *platform*, newest first."""
        backup_dir = self._backup_dir(platform)

        def _list() -> list[Path]:
            if not backup_dir.exists():
                return []
            pattern = f"{platform}_*.tar.gz"
            return sorted(
                backup_dir.glob(pattern),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )

        return await asyncio.to_thread(_list)

    async def get_profile_size(self, platform: str) -> int:
        """Return the total size of the profile directory in bytes."""
        profile_path = self.get_profile_path(platform)

        def _size() -> int:
            if not profile_path.exists():
                return 0
            total = 0
            for f in profile_path.rglob("*"):
                if f.is_file():
                    total += f.stat().st_size
            return total

        return await asyncio.to_thread(_size)
