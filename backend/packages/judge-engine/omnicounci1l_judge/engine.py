"""JudgeEngine — uses external AI APIs for final judgment.

Optional enhancement. System works without it.
Only activates when API keys are configured.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any


from .result import JudgeVerdict

if TYPE_CHECKING:
    from omnicounci1l_core.types import ComparisonContext, RoundContext

logger = logging.getLogger(__name__)


class JudgeEngine:
    """Uses external AI APIs to judge the consensus report.

    This is an OPTIONAL enhancement. The system works without it.
    Only activate when API keys are configured.
    """

    def __init__(self, api_keys: dict[str, str] | None = None) -> None:
        self._api_keys = api_keys or {}

    def has_api_key(self, provider: str) -> bool:
        return provider in self._api_keys

    def set_api_key(self, provider: str, api_key: str) -> None:
        self._api_keys[provider] = api_key

    async def judge(
        self,
        round_ctx: RoundContext,
        comparison_ctx: ComparisonContext,
        consensus_report: Any,
        conflict_result: Any | None = None,
        judge_provider: str = "openai",
    ) -> JudgeVerdict:
        """Use an external AI to judge the consensus.

        Returns JudgeVerdict with assessment.
        If no API key configured, returns degraded verdict.
        """
        if not self.has_api_key(judge_provider):
            return JudgeVerdict(
                judge_id=judge_provider,
                query=round_ctx.query,
                verdict="无法执行裁决：未配置 API Key",
                confidence=0.0,
                generated_at=time.time(),
            )

        prompt = self._build_judge_prompt(
            round_ctx, comparison_ctx, consensus_report, conflict_result
        )

        try:
            result = await self._call_api(judge_provider, prompt)
            return JudgeVerdict(
                judge_id=judge_provider,
                query=round_ctx.query,
                verdict=result.get("verdict", ""),
                reasoning=result.get("reasoning", ""),
                confidence=result.get("confidence", 0.5),
                agrees_with_consensus=result.get("agrees", True),
                additional_insights=result.get("insights", []),
                generated_at=time.time(),
            )
        except Exception as e:
            logger.error("Judge %s failed: %s", judge_provider, e)
            return JudgeVerdict(
                judge_id=judge_provider,
                query=round_ctx.query,
                verdict=f"裁决失败: {str(e)}",
                confidence=0.0,
                generated_at=time.time(),
            )

    def _build_judge_prompt(
        self,
        round_ctx: RoundContext,
        comparison_ctx: ComparisonContext,
        consensus_report: Any,
        conflict_result: Any | None,
    ) -> str:
        resp_text = "\n\n".join(
            f"--- {r.ai_id} ---\n{r.raw_text[:500]}"
            for r in round_ctx.results
            if r.status.value == "success"
        )

        conflict_text = ""
        if conflict_result and conflict_result.has_conflicts:
            conflict_text = "\n冲突点:\n" + "\n".join(
                f"- {c.topic}: {c.root_cause}"
                for c in conflict_result.conflicts[:3]
            )

        return f"""你是一个AI裁判。请根据以下多个AI对同一问题的回答，给出你的最终裁决。

## 问题
{round_ctx.query}

## 各AI的回答
{resp_text}

## 当前共识
结论: {consensus_report.conclusion}
置信度: {consensus_report.confidence}
{conflict_text}

## 请你判断：
1. 你是否同意当前共识？
2. 你的最终裁决是什么？
3. 你的推理过程是什么？

请以JSON格式回答：
{{"verdict": "你的最终裁决", "reasoning": "推理过程", "confidence": 0.0到1.0, "agrees": true或false, "insights": ["额外观点"]}}"""

    async def _call_api(self, provider: str, prompt: str) -> dict:
        """Call external AI API. Override for specific providers."""
        logger.warning("Judge API call not implemented for %s", provider)
        return {
            "verdict": "需要实现API调用",
            "reasoning": "Judge Engine API调用尚未实现",
            "confidence": 0.0,
            "agrees": True,
            "insights": [],
        }
