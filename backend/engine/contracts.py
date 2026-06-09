"""Engine Contracts — public API definitions for Runtime and Query engines.

This file contains ONLY interface definitions, type aliases, enums, dataclasses,
and exception classes.  Zero implementation code.

All interfaces are designed to be compatible with the existing ``BrowserEngine``
abstract base class in ``browser/engine.py`` and the core types in
``shared/types.py``.

Conventions:
    - Protocols define structural subtyping (duck-typing friendly).
    - ABCs define nominal subtyping (explicit inheritance required).
    - Dataclasses are frozen (immutable) following project convention.
    - Enums use ``StrEnum`` for JSON-serialisable values.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pathlib import Path

# Re-export existing types so downstream can import from one place.
from shared.types import SessionState  # noqa: F401, TC001 — re-export for convenience

# ============================================================
#  Section 1: Enums
# ============================================================


class RuntimeState(StrEnum):
    """AI Web Runtime Engine — full lifecycle state machine.

    State transition diagram::

        UNKNOWN
           │
           ▼
        INITIALIZING
           │
           ▼
        PROFILE_LOADING
           │
           ▼
        SESSION_CHECKING ──────────┐
           │                      │
           ▼                      ▼
        READY ──► DEGRADED   LOGIN_REQUIRED ──► RECOVERING
           │         │                            │
           │         ▼                            ├──► READY
           │     RECOVERING                       ├──► LOGIN_REQUIRED
           │         │                            └──► UNAVAILABLE
           │         ▼
           │     UNAVAILABLE
           ▼
        SHUTDOWN

    Allowed transitions are enforced by ``TRANSITIONS`` below.
    Any illegal transition raises ``IllegalStateTransitionError``.
    """

    UNKNOWN = "unknown"
    INITIALIZING = "initializing"
    PROFILE_LOADING = "profile_loading"
    SESSION_CHECKING = "session_checking"
    READY = "ready"
    DEGRADED = "degraded"
    LOGIN_REQUIRED = "login_required"
    RECOVERING = "recovering"
    UNAVAILABLE = "unavailable"
    SHUTDOWN = "shutdown"


# Hard-coded transition matrix.  Values are the set of states reachable
# from the key state.  ``RuntimeStateMachine.transition()`` consults this.
TRANSITIONS: dict[RuntimeState, set[RuntimeState]] = {
    RuntimeState.UNKNOWN:          {RuntimeState.INITIALIZING},
    RuntimeState.INITIALIZING:     {RuntimeState.PROFILE_LOADING, RuntimeState.UNAVAILABLE},
    RuntimeState.PROFILE_LOADING:  {RuntimeState.SESSION_CHECKING, RuntimeState.UNAVAILABLE},
    RuntimeState.SESSION_CHECKING: {RuntimeState.READY, RuntimeState.LOGIN_REQUIRED, RuntimeState.UNAVAILABLE},
    RuntimeState.READY:            {RuntimeState.DEGRADED, RuntimeState.SHUTDOWN, RuntimeState.LOGIN_REQUIRED},
    RuntimeState.DEGRADED:         {RuntimeState.RECOVERING, RuntimeState.READY, RuntimeState.UNAVAILABLE},
    RuntimeState.LOGIN_REQUIRED:   {RuntimeState.RECOVERING, RuntimeState.UNAVAILABLE},
    RuntimeState.RECOVERING:       {RuntimeState.READY, RuntimeState.LOGIN_REQUIRED, RuntimeState.UNAVAILABLE, RuntimeState.SHUTDOWN},
    RuntimeState.UNAVAILABLE:      {RuntimeState.RECOVERING, RuntimeState.SHUTDOWN, RuntimeState.INITIALIZING},
    RuntimeState.SHUTDOWN:         {RuntimeState.INITIALIZING},
}


class HealthStatus(StrEnum):
    """Aggregated health status for a single AI platform runtime.

    Distinct from ``RuntimeState`` — HealthStatus is a *diagnostic* label
    emitted by the HealthMonitor, while RuntimeState is the *control-flow*
    label managed by the state machine.
    """

    HEALTHY = "healthy"          # All checks passed
    DEGRADED = "degraded"        # Page alive but session suspect
    UNHEALTHY = "unhealthy"      # Page or browser unresponsive
    UNKNOWN = "unknown"          # Not yet checked


# ============================================================
#  Section 2: Data classes
# ============================================================


@dataclass(frozen=True)
class StateTransition:
    """Immutable record of a single state-machine transition.

    Stored in ``RuntimeStateMachine.history`` for debugging and audit.
    """

    from_state: RuntimeState
    to_state: RuntimeState
    timestamp: float
    reason: str = ""
    success: bool = True


@dataclass(frozen=True)
class RuntimeHealth:
    """Snapshot of one AI platform's runtime health.

    Produced by ``HealthMonitor.get_health()`` and consumed by the
    Scheduler to decide availability.
    """

    platform: str
    state: RuntimeState
    browser_alive: bool
    page_alive: bool
    session_valid: bool
    last_heartbeat: float = 0.0
    last_error: str | None = None
    recovery_attempts: int = 0
    uptime_seconds: float = 0.0

    @property
    def is_healthy(self) -> bool:
        """True only when every subsystem is green."""
        return (
            self.state == RuntimeState.READY
            and self.browser_alive
            and self.page_alive
            and self.session_valid
        )


@dataclass
class RuntimeMetrics:
    """Per-platform runtime counters — incremented on key paths.

    These are mutable counters; collect via ``MetricsCollector`` for
    Prometheus export.  Reset only at engine boot, never in steady state.
    """

    platform: str
    page_created: int = 0
    page_destroyed: int = 0
    page_lease_acquired: int = 0
    page_lease_released: int = 0
    page_busy_rejections: int = 0
    recovery_started: int = 0
    recovery_succeeded: int = 0
    recovery_failed: int = 0
    recovery_aborted_busy: int = 0
    session_expired: int = 0
    query_total: int = 0
    query_succeeded: int = 0
    query_failed: int = 0
    eviction_started: int = 0
    eviction_completed: int = 0

    def snapshot(self) -> dict[str, int]:
        return {
            "page_created": self.page_created,
            "page_destroyed": self.page_destroyed,
            "page_lease_acquired": self.page_lease_acquired,
            "page_lease_released": self.page_lease_released,
            "page_busy_rejections": self.page_busy_rejections,
            "recovery_started": self.recovery_started,
            "recovery_succeeded": self.recovery_succeeded,
            "recovery_failed": self.recovery_failed,
            "recovery_aborted_busy": self.recovery_aborted_busy,
            "session_expired": self.session_expired,
            "query_total": self.query_total,
            "query_succeeded": self.query_succeeded,
            "query_failed": self.query_failed,
            "eviction_started": self.eviction_started,
            "eviction_completed": self.eviction_completed,
        }


@dataclass(frozen=True)
class QueryRequest:
    """Input to ``QueryEngine.execute()``.

    Carries everything the Query Engine needs — prompt, timeout, retry
    policy — but *no* browser or runtime references.  The Page object
    is passed separately to ``execute()``.
    """

    platform: str                       # "chatgpt" / "gemini" / …
    prompt: str                         # User question
    files: list[str] = field(default_factory=list)  # Attachment paths
    model: str | None = None            # Model override (optional)
    timeout_ms: int = 120_000           # Per-attempt timeout
    max_retries: int = 2                # Max retry attempts
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class QueryResult:
    """Output of ``QueryEngine.execute()``.

    Unified return type for every platform.  ``success`` is True only
    when ``state == QueryState.DONE`` and ``content`` is non-None.
    """

    request: QueryRequest
    state: QueryState  # noqa: F821 — forward ref resolved by __future__.annotations
    content: str | None = None
    images: list[str] = field(default_factory=list)
    thinking: str | None = None          # Chain-of-thought (if exposed)
    model_used: str | None = None        # Actual model name
    elapsed_seconds: float = 0.0
    attempts: int = 0
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.state == QueryState.DONE and self.content is not None


# ============================================================
#  Section 3: Query sub-state enum
# ============================================================


class QueryState(StrEnum):
    """Lifecycle of a single query execution.

    This is *not* a Runtime-level state — it tracks one call to
    ``QueryEngine.execute()`` from submission to completion.
    """

    PENDING = "pending"
    SENDING = "sending"
    WAITING = "waiting"
    EXTRACTING = "extracting"
    DONE = "done"
    RETRYING = "retrying"
    FAILED = "failed"
    TIMEOUT = "timeout"


class PageBusyState(StrEnum):
    """Page lease state — orthogonal to RuntimeState.

    The page can be in one of these sub-states at any time:
      - IDLE:       no query holds the lease, no eviction pending
      - LEASED:     a query holds the lease and is using the page
      - RECOVERING: the runtime is in a recovery round
      - EVICTING:   the page is being torn down and recreated
    """

    IDLE = "idle"
    LEASED = "leased"
    RECOVERING = "recovering"
    EVICTING = "evicting"


# ============================================================
#  Section 4: Exception hierarchy
# ============================================================


class RuntimeEngineError(Exception):
    """Base exception for all Runtime Engine errors."""

    def __init__(self, code: str, message: str, recoverable: bool = False) -> None:
        self.code = code
        self.message = message
        self.recoverable = recoverable
        super().__init__(f"[{code}] {message}")


class IllegalStateTransitionError(RuntimeEngineError):
    """Raised when a state-machine transition is not in ``TRANSITIONS``."""

    def __init__(self, from_state: RuntimeState, to_state: RuntimeState) -> None:
        self.from_state = from_state
        self.to_state = to_state
        allowed = sorted(s.value for s in TRANSITIONS.get(from_state, set()))
        super().__init__(
            "ILLEGAL_TRANSITION",
            f"{from_state.value} -> {to_state.value} not allowed. "
            f"Allowed: {allowed}",
            recoverable=False,
        )


class RuntimeNotReadyError(RuntimeEngineError):
    """Raised when ``get_page()`` is called but state != READY."""

    def __init__(self, current_state: RuntimeState) -> None:
        self.current_state = current_state
        super().__init__(
            "RUNTIME_NOT_READY",
            f"Cannot get page in state {current_state.value}. "
            f"Call ensure_ready() first.",
            recoverable=True,
        )


class RecoveryFailedError(RuntimeEngineError):
    """Raised when all recovery strategies are exhausted."""

    def __init__(self, platform: str, attempts: int) -> None:
        self.platform = platform
        self.attempts = attempts
        super().__init__(
            "RECOVERY_FAILED",
            f"{platform}: all {attempts} recovery attempts failed",
            recoverable=False,
        )


class ProfileError(RuntimeEngineError):
    """Raised on profile creation, backup, or restore failure."""

    def __init__(self, platform: str, message: str) -> None:
        super().__init__(
            "PROFILE_ERROR",
            f"{platform}: {message}",
            recoverable=True,
        )


class PageBusyError(RuntimeEngineError):
    """Raised when the runtime page cannot be leased.

    This happens when:
      - Another query already holds the page lease.
      - The runtime is currently in RECOVERING / EVICTING state.
      - The lease acquisition exceeds the configured timeout.
    """

    def __init__(self, platform: str, reason: str) -> None:
        self.platform = platform
        super().__init__(
            "PAGE_BUSY",
            f"{platform}: page lease unavailable — {reason}",
            recoverable=True,
        )


class RecoveryBusyError(RuntimeEngineError):
    """Raised when a recovery round is aborted because the page is busy."""

    def __init__(self, platform: str, waited_ms: int) -> None:
        self.platform = platform
        self.waited_ms = waited_ms
        super().__init__(
            "RECOVERY_BUSY",
            f"{platform}: recovery aborted after waiting {waited_ms}ms — "
            "page still leased by an active query",
            recoverable=True,
        )


class QueryEngineError(Exception):
    """Base exception for all Query Engine errors."""

    def __init__(self, code: str, message: str, recoverable: bool = False) -> None:
        self.code = code
        self.message = message
        self.recoverable = recoverable
        super().__init__(f"[{code}] {message}")


class QueryTimeoutError(QueryEngineError):
    """Response extraction timed out."""

    def __init__(self, platform: str, timeout_ms: int) -> None:
        super().__init__(
            "QUERY_TIMEOUT",
            f"{platform}: timed out after {timeout_ms}ms",
            recoverable=True,
        )


class SendError(QueryEngineError):
    """Failed to locate input element or send prompt."""

    def __init__(self, platform: str, reason: str) -> None:
        super().__init__(
            "SEND_ERROR",
            f"{platform}: {reason}",
            recoverable=True,
        )


class ExtractError(QueryEngineError):
    """Failed to extract response content from the page."""

    def __init__(self, platform: str, reason: str) -> None:
        super().__init__(
            "EXTRACT_ERROR",
            f"{platform}: {reason}",
            recoverable=True,
        )


class FileUploadError(QueryEngineError):
    """File upload to the AI platform failed."""

    def __init__(self, platform: str, reason: str) -> None:
        super().__init__(
            "FILE_UPLOAD_ERROR",
            f"{platform}: {reason}",
            recoverable=True,
        )


# ============================================================
#  Section 5: Authentication configuration
# ============================================================


class AuthMethod(StrEnum):
    """认证方式枚举。"""
    COOKIE = "cookie"
    OAUTH2 = "oauth2"
    API_KEY = "api_key"
    NONE = "none"


@dataclass(frozen=True)
class CookieAuthConfig:
    """Cookie 认证配置。"""
    domains: list[str]           # ["chat.deepseek.com"]
    names: list[str]             # ["sessionid", "token", "auth"]
    match: str = "prefix"        # "prefix" | "contains" | "exact"


@dataclass(frozen=True)
class OAuthAuthConfig:
    """OAuth2 认证配置。"""
    token_url: str
    client_id: str = ""
    redirect_uri: str = ""
    scopes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ApiKeyAuthConfig:
    """API Key 认证配置。"""
    header_name: str = "Authorization"
    header_prefix: str = "Bearer"
    env_var: str = ""


@dataclass(frozen=True)
class AuthConfig:
    """统一认证配置。"""
    method: AuthMethod
    cookie: CookieAuthConfig | None = None
    oauth: OAuthAuthConfig | None = None
    api_key: ApiKeyAuthConfig | None = None


# ============================================================
#  Section 6: Platform configuration
# ============================================================


@dataclass(frozen=True)
class PlatformConfig:
    """Configuration for a single AI platform's runtime.

    Passed to ``AIRuntimeEngine.__init__()`` and drives boot, heartbeat,
    recovery, and profile behaviour.  All platform-specific knobs live
    here instead of if-else branches.
    """

    name: str                                       # "chatgpt" / "deepseek" / …
    home_url: str                                   # Canonical chat page URL
    login_url: str | None = None                    # Login page URL (defaults to home_url)
    profile_dir: str | None = None                  # Override profile path (default: ~/.omnicouncil/auth/{name}_profile)
    headless: bool = True                           # Browser headless mode
    heartbeat_interval_s: int = 60                  # Heartbeat period (seconds)
    max_recovery_attempts: int = 3                  # Max consecutive recovery attempts before UNAVAILABLE
    recovery_cooldown_s: int = 30                   # Cooldown between recovery rounds
    session_check_mode: str = "offline_then_online" # "offline" | "online" | "offline_then_online"
    extra_browser_args: list[str] = field(default_factory=list)  # Additional Chromium launch args
    extra: dict[str, Any] = field(default_factory=dict)          # Arbitrary platform-specific config
    auth: AuthConfig | None = None                  # Authentication configuration


# ============================================================
#  Section 6: Protocol definitions (structural subtyping)
# ============================================================


@runtime_checkable
class SessionValidator(Protocol):
    """Validates whether a browser page has a live, authenticated session.

    Implementations may use offline methods (Cookie SQLite probe) or
    online methods (navigate + DOM check).  The Protocol is intentionally
    narrow — one method, one return value.
    """

    async def validate(self, page: Any) -> SessionState:
        """Check session validity on *page*.

        Args:
            page: A Playwright ``Page`` object (already navigated).

        Returns:
            ``SessionState.AUTHENTICATED`` if the session is valid,
            ``SessionState.AUTH_EXPIRED`` or ``SessionState.LOGIN_REQUIRED``
            otherwise.

        Raises:
            Should never raise — implementations must catch internally and
            return ``SessionState.UNKNOWN`` on failure.
        """
        ...


@runtime_checkable
class RecoveryStrategy(Protocol):
    """A single recovery step in the recovery chain.

    Strategies are executed in order by ``RecoveryEngine``.  Each
    strategy receives the ``AIRuntimeEngine`` instance and the target
    platform name, attempts one specific recovery action, and returns
    True if the session is valid again.
    """

    name: str
    """Human-readable label, e.g. ``"reload"``, ``"renavigate"``."""

    timeout_s: int
    """Maximum seconds this strategy may take before being cancelled."""

    async def recover(self, engine: AIRuntimeEngine, platform: str) -> bool:
        """Attempt recovery.  Return True if session is restored.

        Args:
            engine: The runtime engine to operate on (provides get_page,
                    state machine, profile manager, etc.).
            platform: The platform identifier (e.g. ``"chatgpt"``).

        Returns:
            True if recovery succeeded and the session is valid again.

        Raises:
            Should not raise — return False on failure so the next
            strategy in the chain can be tried.
        """
        ...


@runtime_checkable
class HealthMonitor(Protocol):
    """Background health monitor for all registered platforms.

    Runs periodic checks (browser alive, page responsive, session valid)
    and updates ``RuntimeHealth`` for each platform.  Emits events via
    ``EventBus`` when health state changes.
    """

    def start(self) -> None:
        """Start the background monitoring loop."""
        ...

    async def stop(self) -> None:
        """Cancel the background loop and await cleanup."""
        ...

    def get_health(self, platform: str) -> RuntimeHealth:
        """Return the latest health snapshot for *platform*.

        Returns a ``RuntimeHealth`` with ``HealthStatus.UNKNOWN`` if
        the platform has never been checked.
        """
        ...

    def get_all_health(self) -> dict[str, RuntimeHealth]:
        """Return health snapshots for all registered platforms."""
        ...


# ============================================================
#  Section 7: ABC definitions (nominal subtyping)
# ============================================================


class ProfileManager(ABC):
    """Manages Chrome profile lifecycle for a single platform.

    Responsibilities:
        - Create profile directories.
        - Backup profiles (tar.gz, retain last N).
        - Restore from backup (with safety rollback).
        - Health-check (Cookie SQLite probe, independent of browser).

    Profile path convention (compatible with existing code)::

        ~/.omnicouncil/auth/{platform}_profile/
            Default/
                Cookies
                ...
            backups/
                {platform}_{timestamp}.tar.gz
    """

    @abstractmethod
    def get_profile_path(self, platform: str) -> Path:
        """Return the profile directory path for *platform*.

        Must not launch a browser or perform I/O — this is a pure
        path computation.

        Args:
            platform: e.g. ``"chatgpt"``

        Returns:
            Absolute path to the profile directory.
        """
        ...

    @abstractmethod
    async def create(self, platform: str) -> Path:
        """Ensure the profile directory exists and return its path.

        Creates parent directories if needed.  Does NOT launch a browser.

        Args:
            platform: e.g. ``"deepseek"``

        Returns:
            Absolute path to the created profile directory.

        Raises:
            ProfileError: If directory creation fails.
        """
        ...

    @abstractmethod
    async def backup(self, platform: str) -> Path:
        """Snapshot the profile directory into a ``.tar.gz`` archive.

        Archives are stored under ``{profile_dir}/backups/``.
        Older backups beyond the retention limit (default 3) are
        automatically deleted.

        Args:
            platform: e.g. ``"gemini"``

        Returns:
            Path to the newly created backup archive.

        Raises:
            ProfileError: If the profile directory does not exist or
                archiving fails.
        """
        ...

    @abstractmethod
    async def restore(self, platform: str, backup_path: Path) -> bool:
        """Restore a profile from a backup archive.

        Before overwriting, the current profile is backed up
        automatically (safety rollback).  After extraction the
        profile directory matches the contents of *backup_path*.

        Args:
            platform: e.g. ``"chatgpt"``
            backup_path: Path to a ``.tar.gz`` backup file.

        Returns:
            True on success.

        Raises:
            ProfileError: If *backup_path* does not exist or
                extraction fails.
        """
        ...

    @abstractmethod
    async def health_check(self, platform: str) -> bool:
        """Quick offline health check — no browser launched.

        Checks:
            1. Profile directory exists and is non-empty.
            2. Cookie file exists and contains unexpired auth cookies
               for the platform's domain.

        This reuses the SQLite probe logic currently in
        ``EmbeddedEngine._has_valid_session`` but depends only on
        the file path, not on an engine instance.

        Args:
            platform: e.g. ``"deepseek"``

        Returns:
            True if the profile appears healthy.
        """
        ...


class QueryAdapter(ABC):
    """Per-platform query logic — the "right hand" of Query Engine.

    Each AI platform implements this class to handle:
        - Locating the input element (``_find_input``)
        - Sending a prompt (``send_prompt``)
        - Waiting for the response to stabilise (``wait_for_response``)
        - Extracting the result (``extract_result``)

    The Query Engine owns the orchestration (ensure ready → send → wait
    → extract); the adapter owns the DOM-specific details.

    Design rule: QueryAdapter must NEVER hold a reference to
    ``BrowserEngine`` or ``AIRuntimeEngine``.  The ``Page`` object is
    passed in from the outside.
    """

    @abstractmethod
    async def send_prompt(self, page: Any, request: QueryRequest) -> None:
        """Send *request.prompt* to the AI page.

        Steps:
            1. Locate the input element.
            2. Clear any existing text.
            3. Type the prompt.
            4. Press Enter or click the send button.

        Args:
            page: A Playwright ``Page`` — already navigated, session valid.
            request: The query request (prompt, files, model, etc.).

        Raises:
            SendError: Input element not found or interaction failed.
            FileUploadError: If ``request.files`` is non-empty and
                upload fails.
        """
        ...

    @abstractmethod
    async def wait_for_response(self, page: Any, timeout_ms: int) -> None:
        """Block until the AI finishes generating its response.

        Strategies (implementation-specific):
            - Poll for "stop generating" button disappearance.
            - Poll for content stabilisation (N seconds unchanged).
            - Poll for loading indicator removal.

        Args:
            page: A Playwright ``Page``.
            timeout_ms: Maximum wait in milliseconds.

        Raises:
            QueryTimeoutError: Response did not stabilise in time.
        """
        ...

    @abstractmethod
    async def extract_result(self, page: Any) -> dict[str, Any]:
        """Extract the AI's response from the page DOM.

        Returns:
            A dict with keys:
                - ``content`` (str): The main response text.
                - ``images`` (list[str]): URLs of response images.
                - ``thinking`` (str | None): Chain-of-thought text.
                - ``model`` (str | None): Model name if displayed.

        Raises:
            ExtractError: If no response content can be found.
        """
        ...

    async def pre_flight_check(self, page: Any) -> tuple[bool, str]:  # noqa: B027
        """Quick sanity check before operating on *page*.

        Default implementation checks:
            1. Page is not closed.
            2. URL is not a login/error page.
            3. Cloudflare challenge is not blocking.

        Override for platform-specific checks (e.g. DOM-based login
        detection for 千问).

        Args:
            page: A Playwright ``Page``.

        Returns:
            ``(ok, reason)`` — ``ok=False`` means the caller should
            abort.  ``reason`` is a short label like ``"login_required"``
            or ``"cloudflare_challenge"``.
        """
        # Default: page alive + URL not obviously broken.
        ...

    async def abort_current(self, page: Any) -> None:  # noqa: B027
        """Abort the current in-progress response generation.

        Default implementation clicks the "Stop" / "停止" button if
        visible.  Override for platform-specific behaviour.

        Args:
            page: A Playwright ``Page``.
        """
        ...


# ============================================================
#  Section 8: AIRuntimeEngine class definition
# ============================================================


class AIRuntimeEngine:
    """AI Web Runtime Engine — the "left hand" of the architecture.

    Responsibility boundary::

        ✅ Boot / shutdown browser
        ✅ Manage profiles (create / backup / restore)
        ✅ Validate sessions (offline + online)
        ✅ Maintain state machine (10 states)
        ✅ Run heartbeat health checks
        ✅ Execute automatic recovery chain
        ✅ Cache and manage Page lifecycle

        ❌ Send prompts
        ❌ Extract responses
        ❌ Parse content

    The single public entry point for callers is ``ensure_ready()``.
    It is idempotent: if already READY it returns immediately; if
    UNINITIALIZED it boots; if degraded it attempts recovery.

    Usage::

        engine = AIRuntimeEngine(config)
        state = await engine.ensure_ready()   # blocks until READY or raises
        page = engine.get_page()              # only valid when READY
    """

    def __init__(self, config: PlatformConfig) -> None:
        """Initialise the engine in UNDEFINED state.

        Call ``boot()`` or ``ensure_ready()`` to start.

        Args:
            config: Platform-specific configuration.
        """
        ...

    # ── Lifecycle ──────────────────────────────────────────

    @abstractmethod
    async def boot(self) -> RuntimeState:
        """Cold-start the engine.

        Transition sequence::

            UNKNOWN → INITIALIZING → PROFILE_LOADING
            → SESSION_CHECKING → READY (or LOGIN_REQUIRED)

        On failure at any phase, transitions to UNAVAILABLE.

        Returns:
            The resulting ``RuntimeState`` after boot completes.

        Raises:
            ProfileError: If profile creation fails.
            RuntimeEngineError: On unexpected browser launch failure.
        """
        ...

    @abstractmethod
    async def shutdown(self) -> None:
        """Gracefully shut down: stop heartbeat, close browser, transition to SHUTDOWN.

        Safe to call multiple times.  After shutdown, call ``boot()``
        to restart.
        """
        ...

    # ── Core interface ─────────────────────────────────────

    @abstractmethod
    async def ensure_ready(self) -> RuntimeState:
        """Idempotent entry point — blocks until READY or raises.

        Behaviour:
            - ``UNINITIALIZED`` / ``UNKNOWN`` → calls ``boot()``
            - ``READY`` → returns immediately
            - ``DEGRADED`` / ``LOGIN_REQUIRED`` / ``UNAVAILABLE``
              → attempts recovery
            - ``SHUTDOWN`` → re-boots

        Returns:
            The current ``RuntimeState`` (guaranteed READY on success).

        Raises:
            RecoveryFailedError: If all recovery strategies fail.
        """
        ...

    @abstractmethod
    def get_page(self) -> Any:
        """Return the cached Playwright Page.

        Only valid when state is READY.  The Page is lazily created
        during ``boot()`` and cached until eviction or shutdown.

        Returns:
            A Playwright ``Page`` object.

        Raises:
            RuntimeNotReadyError: If state != READY.
        """
        ...

    @abstractmethod
    async def check_health(self) -> RuntimeHealth:
        """Run a full health check and return a snapshot.

        Checks:
            1. Browser process alive.
            2. Page not closed and responsive (``document.readyState``).
            3. Session valid (via ``SessionValidator``).

        Does NOT trigger recovery — use ``attempt_recovery()`` for that.

        Returns:
            A ``RuntimeHealth`` snapshot.
        """
        ...

    @abstractmethod
    async def attempt_recovery(self) -> bool:
        """Execute the recovery strategy chain.

        Sets state to RECOVERING, then tries each strategy in order:
            1. Reload (15s)
            2. Re-navigate (20s)
            3. New tab (20s)
            4. Restart browser (30s)

        On success: state → READY, ``recovery_attempts`` reset to 0.
        On total failure: state → UNAVAILABLE, raises ``RecoveryFailedError``.

        Returns:
            True if recovery succeeded.

        Raises:
            RecoveryFailedError: All strategies exhausted.
        """
        ...

    # ── Introspection ──────────────────────────────────────

    @property
    @abstractmethod
    def state(self) -> RuntimeState:
        """Current runtime state (read-only)."""
        ...

    @property
    @abstractmethod
    def platform(self) -> str:
        """Platform identifier, e.g. ``"chatgpt"``."""
        ...

    @property
    @abstractmethod
    def state_history(self) -> list[StateTransition]:
        """Ordered list of all state transitions since last boot."""
        ...

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """True if the underlying browser process is alive."""
        ...

    # ── Sub-component access (for testing / advanced use) ──

    @abstractmethod
    def get_profile_manager(self) -> ProfileManager:
        """Return the profile manager instance."""
        ...

    @abstractmethod
    def get_session_validator(self) -> SessionValidator:
        """Return the session validator instance."""
        ...

    @abstractmethod
    def get_health_monitor(self) -> HealthMonitor:
        """Return the health monitor instance."""
        ...


# ============================================================
#  Section 9: RuntimeStateMachine protocol
# ============================================================


@runtime_checkable
class RuntimeStateMachine(Protocol):
    """State machine that governs ``RuntimeState`` transitions.

    Implementations must:
        - Consult ``TRANSITIONS`` before every transition.
        - Raise ``IllegalStateTransitionError`` on illegal moves.
        - Log every transition via ``logging.getLogger(__name__)``.
        - Record each transition as a ``StateTransition`` in history.
        - Support an optional per-transition callback.
    """

    current: RuntimeState
    """The current state."""

    history: list[StateTransition]
    """Ordered list of all transitions since creation."""

    def transition(self, new_state: RuntimeState, reason: str = "") -> None:
        """Attempt a state transition.

        Args:
            new_state: Target state.
            reason: Human-readable reason for the transition.

        Raises:
            IllegalStateTransitionError: If the transition is not in
                ``TRANSITIONS[current]``.
        """
        ...

    def can_transition(self, new_state: RuntimeState) -> bool:
        """Check whether *new_state* is reachable from current state.

        Non-mutating — does not perform the transition.
        """
        ...

    def reset(self, initial_state: RuntimeState = RuntimeState.UNKNOWN) -> None:
        """Reset the machine to *initial_state* and clear history."""
        ...


# ============================================================
#  Section 10: RuntimeRegistry protocol
# ============================================================


@runtime_checkable
class RuntimeRegistry(Protocol):
    """Registry mapping platform IDs to ``AIRuntimeEngine`` instances.

    Replaces the current pattern of storing engines in ``AppState``
    as ad-hoc attributes.  The Scheduler and AIAccessManager use
    this to look up the correct runtime for each AI.
    """

    def register(self, platform: str, engine: AIRuntimeEngine) -> None:
        """Register an engine for *platform*.  Overwrites if already present."""
        ...

    def unregister(self, platform: str) -> None:
        """Remove the engine for *platform*.  No-op if not found."""
        ...

    def get(self, platform: str) -> AIRuntimeEngine | None:
        """Return the engine for *platform*, or None."""
        ...

    def get_all(self) -> dict[str, AIRuntimeEngine]:
        """Return all registered engines."""
        ...

    def all(self) -> dict[str, AIRuntimeEngine]:
        """Alias for get_all() — convenience for iteration."""
        ...

    def get_platforms(self) -> list[str]:
        """Return all registered platform IDs."""
        ...

    async def ensure_all_ready(self) -> dict[str, RuntimeState]:
        """Call ``ensure_ready()`` on every registered engine.

        Returns a mapping of platform → resulting state.
        Engines that fail are mapped to ``UNAVAILABLE``.
        """
        ...

    async def shutdown_all(self) -> None:
        """Shut down every registered engine."""
        ...
