"""Consensus result models — immutable dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ConsensusPoint:
    """一个达成共识的观点。"""
    point_id: str
    statement: str
    supporting_ais: list[str]
    agreement_ratio: float  # 0-1
    evidence: list[str]
    confidence: float  # 0-1


@dataclass(frozen=True)
class DisagreementPosition:
    """分歧中的一个立场。"""
    ai_id: str
    stance: str
    evidence: str


@dataclass(frozen=True)
class DisagreementPoint:
    """一个存在分歧的观点。"""
    point_id: str
    dimension: str
    positions: list[DisagreementPosition]
    severity: float  # 0-1
    diff_type: str  # factual/evaluative/methodological/recommendational
    resolvable: bool


@dataclass(frozen=True)
class ConsensusRecommendation:
    """基于共识/分歧的建议。"""
    recommendation_id: str
    text: str
    basis: str  # consensus/disagreement/unique_insight
    priority: str  # high/medium/low


@dataclass(frozen=True)
class ConsensusSummaryStats:
    """报告统计摘要。"""
    total_ais: int
    successful_ais: int
    total_consensus_points: int
    total_disagreements: int
    total_unique_insights: int
    avg_pairwise_similarity: float
    top_agreement_dimension: str
    top_disagreement_dimension: str


@dataclass(frozen=True)
class ConsensusReport:
    """最终共识报告。"""
    task_id: str
    query: str
    generated_at: float
    conclusion: str
    confidence: float  # 0-1
    consensus_points: list[ConsensusPoint]
    disagreements: list[DisagreementPoint]
    unique_insights: list  # list[UniqueInsight] from shared.types
    recommendations: list[ConsensusRecommendation]
    participant_ais: list[str]
    agreement_level: str  # high/medium/low/divergent
    summary_stats: ConsensusSummaryStats
    degraded: str | None  # single_source/no_comparison/None
