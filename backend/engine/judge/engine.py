"""Judge engine — uses external AI APIs for final judgment.

This is the V2-C component that requires API keys.
Can be used as an optional enhancement on top of the rule-based V2-A/V2-B analysis.
"""

from __future__ import annotations

import logging
from typing import Any

from ..consensus.result import ConsensusReport
from .result import JudgeVerdict

logger = logging.getLogger(__name__)


class JudgeEngine:
    """Uses external AI APIs to judge the consensus report.

    This is an OPTIONAL enhancement. The system works without it.
    Only activate when API keys are configured.
    """

    def __init__(self, api_keys: dict[str, str] | None = None):
        self._api_keys = api_keys or {}
        self._judges: dict[str, Any] = {}

    def has_api_key(self, provider: str) -> bool:
        return provider in self._api_keys

    def set_api_key(self, provider: str, api_key: str) -> None:
        self._api_keys[provider] = api_key

    async def judge(
        self,
        query: str,
        responses: list[dict],
        consensus: ConsensusReport,
        judge_provider: str = "openai",
    ) -> JudgeVerdict:
        """Use an external AI to judge the consensus.

        Args:
            query: Original user question
            responses: List of AI responses [{provider_id, content}]
            consensus: The consensus report to judge
            judge_provider: Which AI to use as judge ("openai", "claude", "gemini")

        Returns:
            JudgeVerdict with the judge's assessment
        """
        if not self.has_api_key(judge_provider):
            return JudgeVerdict(
                judge_id=judge_provider,
                query=query,
                verdict="无法执行裁决：未配置 API Key",
                confidence=0.0,
            )

        # Build the judge prompt
        prompt = self._build_judge_prompt(query, responses, consensus)

        # Call the external API
        try:
            result = await self._call_api(judge_provider, prompt)
            return JudgeVerdict(
                judge_id=judge_provider,
                query=query,
                verdict=result.get("verdict", ""),
                reasoning=result.get("reasoning", ""),
                confidence=result.get("confidence", 0.5),
                agrees_with_consensus=result.get("agrees", True),
                additional_insights=result.get("insights", []),
            )
        except Exception as e:
            logger.error("Judge %s failed: %s", judge_provider, e)
            return JudgeVerdict(
                judge_id=judge_provider,
                query=query,
                verdict=f"裁决失败: {str(e)}",
                confidence=0.0,
            )

    def _build_judge_prompt(
        self,
        query: str,
        responses: list[dict],
        consensus: ConsensusReport,
    ) -> str:
        """Build the prompt for the AI judge."""
        resp_text = "\n\n".join(
            f"--- {r['provider_id']} ---\n{r['content']}"
            for r in responses
        )

        return f"""你是一个AI裁判。请根据以下多个AI对同一问题的回答，给出你的最终裁决。

## 问题
{query}

## 各AI的回答
{resp_text}

## 当前共识
结论: {consensus.conclusion}
置信度: {consensus.confidence}
关键点: {', '.join(consensus.key_points)}

## 请你判断：
1. 你是否同意当前共识？
2. 你的最终裁决是什么？
3. 你的推理过程是什么？
4. 有没有其他AI没提到的重要观点？

请以JSON格式回答：
{{
  "verdict": "你的最终裁决",
  "reasoning": "你的推理过程",
  "confidence": 0.0到1.0的置信度,
  "agrees": true或false,
  "insights": ["额外观点1", "额外观点2"]
}}"""

    async def _call_api(self, provider: str, prompt: str) -> dict:
        """Call external AI API. Override for specific providers."""
        # Placeholder — implement actual API calls
        # For now, return a mock response
        logger.warning("Judge API call not implemented for %s", provider)
        return {
            "verdict": "需要实现API调用",
            "reasoning": "Judge Engine API调用尚未实现",
            "confidence": 0.0,
            "agrees": True,
            "insights": [],
        }
