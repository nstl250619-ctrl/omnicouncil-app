"""omnicounci1l-consensus — consensus analysis engine for OmniCouncil."""

from .engine import ConsensusEngine
from .result import (
    ConsensusPoint,
    ConsensusRecommendation,
    ConsensusReport,
    ConsensusSummaryStats,
    DisagreementPoint,
    DisagreementPosition,
)

__version__ = "1.0.0"
__all__ = [
    "ConsensusEngine",
    "ConsensusPoint",
    "ConsensusRecommendation",
    "ConsensusReport",
    "ConsensusSummaryStats",
    "DisagreementPoint",
    "DisagreementPosition",
]
