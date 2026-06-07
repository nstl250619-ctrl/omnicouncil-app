"""omnicounci1l-core — shared types and configuration for OmniCouncil engines."""

from .types import (
    AIResponse,
    AIStatus,
    CircuitState,
    CollectorProgress,
    ComparisonContext,
    ComparisonMetrics,
    DifferenceItem,
    NormalizedResponse,
    ProviderStatus,
    ResultStatus,
    RoundContext,
    RoundContextSummary,
    SemanticUnit,
    SessionState,
    SimilarityMatrix,
    SubmitOptions,
    TaskHandle,
    TaskMode,
    TaskProgress,
    TaskStatus,
    TaskStatusInfo,
    UniqueInsight,
    generate_id,
)
from .config import ComparisonConfig, RateLimitConfig, RetryConfig, SchedulerConfig

__version__ = "1.0.0"
