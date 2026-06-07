"""ConflictEngine — analyzes why AIs disagree.

Stateless. Pure function: RoundContext + ComparisonContext + ConsensusReport → ConflictResult.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from omnicounci1l_core.types import generate_id

from .result import ConflictPoint, ConflictPosition, ConflictResult

if TYPE_CHECKING:
    from omnicounci1l_core.types import ComparisonContext, RoundContext

logger = logging.getLogger(__name__)


class ConflictEngine:
    """Analyzes conflicts between AI responses.

    Takes comparison and consensus results and deepens the analysis:
    - Why do AIs disagree?
    - What are the root causes?
    - Are the conflicts resolvable?
    """

    def analyze(
        self,
        round_ctx: RoundContext,
        comparison_ctx: ComparisonContext,
        consensus_report: Any | None = None,
    ) -> ConflictResult:
        """Analyze conflicts from comparison results."""
        start = time.time()
        conflicts = []

        # Analyze each disagreement from comparison
        for diff in comparison_ctx.differences:
            conflict = self._analyze_difference(diff)
            if conflict:
                conflicts.append(conflict)

        # Analyze response length variance
        successful = [r for r in round_ctx.results if r.status.value == "success"]
        if len(successful) >= 2:
            lengths = [len(r.raw_text) for r in successful]
            avg_len = sum(lengths) / len(lengths)
            if max(lengths) > avg_len * 3:
                positions = [
                    ConflictPosition(
                        ai_id=r.ai_id,
                        stance=f"回复长度: {len(r.raw_text)}字",
                    )
                    for r in successful
                ]
                conflicts.append(ConflictPoint(
                    conflict_id=generate_id("cf"),
                    topic="回复详细度差异",
                    positions=positions,
                    root_cause="不同AI对问题的理解深度不同",
                    severity=0.3,
                    resolvable=True,
                ))

        # Overall conflict level
        overall = sum(c.severity for c in conflicts) / len(conflicts) if conflicts else 0.0

        # Summary
        summary = self._generate_summary(conflicts)

        elapsed = time.time() - start
        logger.info(
            "Conflict analysis for task %s in %.2fs: %d conflicts, level=%.2f",
            round_ctx.task_id, elapsed, len(conflicts), overall,
        )

        return ConflictResult(
            task_id=round_ctx.task_id,
            query=round_ctx.query,
            conflicts=conflicts,
            summary=summary,
            overall_conflict_level=round(overall, 3),
            generated_at=time.time(),
        )

    def _analyze_difference(self, diff) -> ConflictPoint | None:
        """Analyze a single difference to find root cause."""
        if not diff.involved_ais:
            return None

        positions = []
        for ai_id, stance in diff.involved_ais:
            positions.append(ConflictPosition(
                ai_id=ai_id,
                stance=stance[:100],
            ))

        # Root cause analysis
        stances = [s for _, s in diff.involved_ais]
        all_text = " ".join(stances)

        if any(w in all_text for w in ["数据", "事实", "统计", "source", "data"]):
            root_cause = "事实性分歧：不同AI引用了不同的数据来源"
        elif any(w in all_text for w in ["我认为", "我觉得", "个人观点", "I think"]):
            root_cause = "观点性分歧：不同AI有不同的价值判断"
        elif any(w in all_text for w in ["方法", "策略", "步骤", "approach", "method"]):
            root_cause = "方法论分歧：不同AI推荐不同的解决路径"
        else:
            root_cause = "不同AI基于不同训练数据和推理路径得出不同结论"

        return ConflictPoint(
            conflict_id=generate_id("cf"),
            topic=diff.dimension,
            positions=positions,
            root_cause=root_cause,
            severity=round(diff.strength, 3),
            resolvable=diff.strength < 0.7,
        )

    def _generate_summary(self, conflicts: list[ConflictPoint]) -> str:
        if not conflicts:
            return "未发现显著冲突。所有AI观点基本一致。"

        severe = [c for c in conflicts if c.severity >= 0.7]
        if severe:
            return f"发现 {len(conflicts)} 个冲突点，其中 {len(severe)} 个严重冲突。建议重点关注这些分歧。"
        return f"发现 {len(conflicts)} 个轻度冲突点。整体分歧可控。"
