"""Core data types for OmniCouncil layers 1-4.

All types are immutable dataclasses (frozen=True) following the project's
immutability principle.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

# ========== Layer 1: AI Access Layer ==========

class AIStatus(StrEnum):
    INITIALIZING = "initializing"
    READY = "ready"
    BUSY = "busy"
    LOGIN_REQUIRED = "login_required"
    CAPTCHA_REQUIRED = "captcha_required"
    ERROR = "error"
    RATE_LIMITED = "rate_limited"
    CIRCUIT_OPEN = "circuit_open"


class SessionState(StrEnum):
    """Precise session authentication state for each AI provider.

    Replaces the previous boolean ``authenticated`` which conflated
    "cookie file exists" with "session is valid".
    """
    UNKNOWN = "unknown"          # Not yet checked (initial state)
    AUTHENTICATED = "authenticated"  # Verified valid via cookie/session check
    AUTH_EXPIRED = "expired"     # Session known to be expired
    LOGIN_REQUIRED = "login_required"  # Online check confirmed login page
    REAUTH_IN_PROGRESS = "reauthing"  # User is being prompted to re-login


class CircuitState(StrEnum):
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Tripped, rejecting requests
    HALF_OPEN = "half_open"  # Testing recovery


@dataclass(frozen=True)
class ProviderStatus:
    ai_id: str
    ai_name: str
    status: AIStatus = AIStatus.INITIALIZING
    last_check_at: float = 0.0
    consecutive_failures: int = 0


@dataclass(frozen=True)
class AIResponse:
    success: bool
    ai_id: str
    task_id: str
    content: str
    model: str = ""
    timestamp: float = 0.0
    duration: float = 0.0
    word_count: int = 0
    has_code_block: bool = False
    has_table: bool = False
    is_truncated: bool = False
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class NormalizedResponse:
    """Standardized AI response after normalization."""
    main_text: str
    code_blocks: list[tuple[str, str]] = field(default_factory=list)  # (language, code)
    paragraphs: list[str] = field(default_factory=list)
    word_count: int = 0
    detected_language: str | None = None
    has_markdown: bool = False


@dataclass(frozen=True)
class SubmitOptions:
    timeout_ms: int = 120000
    retry_count: int = 2
    on_stream_chunk: Any = None  # Optional callback


# ========== Layer 2: Scheduler ==========

class TaskMode(StrEnum):
    PARALLEL = "parallel"
    SEQUENTIAL = "sequential"


class TaskStatus(StrEnum):
    CREATED = "created"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"
    CANCELLED = "cancelled"


class SubTaskStatus(StrEnum):
    QUEUED = "queued"
    DISPATCHING = "dispatching"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class TaskProgress:
    total_ais: int = 0
    completed_ais: int = 0
    failed_ais: int = 0


@dataclass(frozen=True)
class TaskStatusInfo:
    task_id: str
    status: TaskStatus = TaskStatus.CREATED
    progress: TaskProgress = field(default_factory=TaskProgress)
    created_at: float = 0.0
    updated_at: float = 0.0


@dataclass(frozen=True)
class QueryRequest:
    query: str
    selected_ai_ids: list[str]
    mode: TaskMode = TaskMode.PARALLEL
    timeout_ms: int = 120000
    priority: int = 0


@dataclass(frozen=True)
class TaskHandle:
    task_id: str
    status: TaskStatus = TaskStatus.CREATED
    created_at: float = 0.0


@dataclass(frozen=True)
class AIAvailability:
    available: list[tuple[str, str]] = field(default_factory=list)  # (ai_id, ai_name)
    unavailable: list[tuple[str, str]] = field(default_factory=list)  # (ai_id, reason)
    mode: str = "strict"


# ========== Layer 3: Result Collection ==========

class ResultStatus(StrEnum):
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class AiResult:
    ai_id: str
    task_id: str
    round_number: int
    status: ResultStatus
    raw_text: str
    normalized: NormalizedResponse
    start_time: float = 0.0
    end_time: float = 0.0
    duration: float = 0.0
    error: str | None = None
    prompt_used: str = ""
    model: str = ""


@dataclass(frozen=True)
class RoundContextSummary:
    total_ais: int = 0
    success_count: int = 0
    failure_count: int = 0
    timeout_count: int = 0
    completed_at: float = 0.0


@dataclass(frozen=True)
class RoundContext:
    task_id: str
    round_number: int
    query: str
    execution_mode: TaskMode
    results: list[AiResult]
    summary: RoundContextSummary = field(default_factory=RoundContextSummary)
    created_at: float = 0.0


@dataclass(frozen=True)
class CollectorProgress:
    task_id: str
    completed_count: int
    total_count: int
    percentage: float
    latest_ai_id: str = ""
    latest_status: str = ""


# ========== Layer 4: Comparison Analysis ==========

@dataclass(frozen=True)
class SemanticUnit:
    unit_id: str
    source_ai_id: str
    content: str
    paragraph_index: int = 0
    unit_type: str = "paragraph"


@dataclass(frozen=True)
class SimilarityMatrix:
    ai_ids: list[str] = field(default_factory=list)
    pairwise_similarities: list[list[float]] = field(default_factory=list)
    unit_matrix: list[list[float]] = field(default_factory=list)
    unit_index: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DifferenceItem:
    id: str
    dimension: str
    involved_ais: list[tuple[str, str]] = field(default_factory=list)  # (ai_id, stance)
    strength: float = 0.0
    diff_type: str = "evaluative"
    related_unit_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class UniqueInsight:
    unit_id: str
    ai_id: str
    content: str
    novelty_score: float = 0.0
    potential_importance: str = "low"


@dataclass(frozen=True)
class ComparisonMetrics:
    total_units: int = 0
    overall_divergence: float = 0.0
    pairwise_similarities: list[tuple[str, str, float]] = field(default_factory=list)
    top_difference_dimension: str = ""


@dataclass(frozen=True)
class ComparisonContext:
    task_id: str
    round_number: int
    query: str
    source_context_id: str
    generated_at: float = 0.0
    participant_ais: list[tuple[str, int]] = field(default_factory=list)  # (ai_id, unit_count)
    semantic_units: list[SemanticUnit] = field(default_factory=list)
    similarity_matrix: SimilarityMatrix = field(default_factory=SimilarityMatrix)
    differences: list[DifferenceItem] = field(default_factory=list)
    unique_insights: list[UniqueInsight] = field(default_factory=list)
    metrics: ComparisonMetrics = field(default_factory=ComparisonMetrics)
    degraded: str | None = None


# ========== Utility ==========

def generate_id(prefix: str = "id") -> str:
    """Generate a unique ID with a prefix."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"
