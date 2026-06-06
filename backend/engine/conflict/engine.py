"""Conflict engine — analyzes why AIs disagree."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .result import ConflictPoint, ConflictResult

if TYPE_CHECKING:
    from ..collector.response import AIResponse
    from ..comparison.result import ComparisonResult

logger = logging.getLogger(__name__)


class ConflictEngine:
    """Analyzes conflicts between AI responses.

    Takes comparison results and deepens the analysis:
    - Why do AIs disagree?
    - What are the root causes?
    - Are the conflicts resolvable?
    """

    def analyze(
        self,
        task_id: str,
        query: str,
        responses: list[AIResponse],
        comparison: ComparisonResult,
    ) -> ConflictResult:
        """Analyze conflicts from comparison results."""
        conflicts = []

        # Analyze each disagreement from comparison
        for disagreement in comparison.disagreements:
            conflict = self._analyze_disagreement(disagreement, responses)
            if conflict:
                conflicts.append(conflict)

        # Detect additional conflicts by response length variance
        if len(responses) >= 2:
            lengths = [len(r.content) for r in responses]
            avg_len = sum(lengths) / len(lengths)
            if max(lengths) > avg_len * 3:
                conflicts.append(ConflictPoint(
                    topic="回复详细度差异",
                    positions=[
                        {"provider_id": r.provider_id, "stance": f"回复长度: {len(r.content)}字"}
                        for r in responses
                    ],
                    root_cause="不同AI对问题的理解深度不同",
                    severity=0.3,
                    resolvable=True,
                ))

        # Calculate overall conflict level
        overall = sum(c.severity for c in conflicts) / len(conflicts) if conflicts else 0.0

        # Generate summary
        summary = self._generate_summary(conflicts, responses)

        return ConflictResult(
            task_id=task_id,
            query=query,
            conflicts=conflicts,
            summary=summary,
            overall_conflict_level=overall,
        )

    def _analyze_disagreement(self, disagreement, responses: list[AIResponse]) -> ConflictPoint | None:
        """Analyze a single disagreement to find root cause."""
        if not disagreement.positions:
            return None

        # Simple root cause analysis
        root_cause = "不同AI基于不同训练数据和推理路径得出不同结论"

        if len(disagreement.positions) >= 2:
            stances = [p.get("stance", "") for p in disagreement.positions]
            # Check if it's a factual vs opinion disagreement
            if any(w in " ".join(stances) for w in ["数据", "事实", "统计"]):
                root_cause = "事实性分歧：不同AI引用了不同的数据来源"
            elif any(w in " ".join(stances) for w in ["我认为", "我觉得", "个人观点"]):
                root_cause = "观点性分歧：不同AI有不同的价值判断"

        return ConflictPoint(
            topic=disagreement.topic,
            positions=disagreement.positions,
            root_cause=root_cause,
            severity=disagreement.severity,
            resolvable=True,
        )

    def _generate_summary(self, conflicts: list[ConflictPoint], responses: list[AIResponse]) -> str:
        if not conflicts:
            return "未发现显著冲突。所有AI观点基本一致。"

        severe = [c for c in conflicts if c.severity >= 0.7]
        if severe:
            return f"发现 {len(conflicts)} 个冲突点，其中 {len(severe)} 个严重冲突。建议重点关注这些分歧。"
        return f"发现 {len(conflicts)} 个轻度冲突点。整体分歧可控。"
