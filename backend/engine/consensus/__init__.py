"""Consensus engine — generates consensus reports from comparison results."""
from .engine import ConsensusEngine
from .result import (
    ConsensusPoint,
    ConsensusRecommendation,
    ConsensusReport,
    ConsensusSummaryStats,
    DisagreementPoint,
    DisagreementPosition,
)

__all__ = [
    "ConsensusEngine",
    "ConsensusPoint",
    "ConsensusRecommendation",
    "ConsensusReport",
    "ConsensusSummaryStats",
    "DisagreementPoint",
    "DisagreementPosition",
]
