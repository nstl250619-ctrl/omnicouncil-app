"""Comparison engine — rule-based analysis without API keys."""

from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any

from ..collector.response import AIResponse
from .result import Agreement, ComparisonResult, Disagreement

logger = logging.getLogger(__name__)


class ComparisonEngine:
    """Compares multiple AI responses to find agreements and disagreements.

    Uses rule-based text analysis (no API keys needed):
    - Keyword extraction
    - Sentiment analysis (simple)
    - Sentence-level similarity
    """

    def analyze(self, task_id: str, query: str, responses: list[AIResponse]) -> ComparisonResult:
        """Analyze responses and find agreements/disagreements."""
        if len(responses) < 2:
            return ComparisonResult(
                task_id=task_id,
                query=query,
                summary="需要至少2个AI的回复才能进行对比分析",
            )

        # Extract keywords from each response
        keywords_per_provider = {}
        for resp in responses:
            keywords_per_provider[resp.provider_id] = self._extract_keywords(resp.content)

        # Find common keywords (potential agreements)
        all_keywords = list(keywords_per_provider.values())
        common = set(all_keywords[0])
        for kw in all_keywords[1:]:
            common &= kw

        # Find unique keywords per provider (potential disagreements)
        unique_per_provider = {}
        for pid, kws in keywords_per_provider.items():
            unique = kws - set().union(*[v for k, v in keywords_per_provider.items() if k != pid])
            if unique:
                unique_per_provider[pid] = unique

        # Build agreements
        agreements = []
        if common:
            agreements.append(Agreement(
                topic="共同关注点",
                description=f"所有AI都提到了: {', '.join(list(common)[:5])}",
                supporting_providers=[r.provider_id for r in responses],
                confidence=min(1.0, len(common) / 5),
            ))

        # Check for yes/no consensus
        yes_providers = []
        no_providers = []
        for resp in responses:
            first_sentence = resp.content.split('。')[0].split('.')[0].split('\n')[0]
            if any(w in first_sentence for w in ['是', '对', 'Yes', 'yes', '可以', '适合', '推荐']):
                yes_providers.append(resp.provider_id)
            elif any(w in first_sentence for w in ['否', '不', 'No', 'no', '不适合', '不推荐']):
                no_providers.append(resp.provider_id)

        if len(yes_providers) > len(no_providers) and len(yes_providers) >= 2:
            agreements.append(Agreement(
                topic="倾向性共识",
                description=f"多数AI倾向于肯定回答",
                supporting_providers=yes_providers,
                confidence=len(yes_providers) / len(responses),
            ))
        elif len(no_providers) > len(yes_providers) and len(no_providers) >= 2:
            agreements.append(Agreement(
                topic="倾向性共识",
                description=f"多数AI倾向于否定回答",
                supporting_providers=no_providers,
                confidence=len(no_providers) / len(responses),
            ))

        # Build disagreements
        disagreements = []
        if unique_per_provider:
            for pid, keywords in unique_per_provider.items():
                if len(keywords) >= 2:
                    disagreements.append(Disagreement(
                        topic=f"{pid}的独特观点",
                        positions=[{
                            "provider_id": pid,
                            "stance": f"提出了独特关键词: {', '.join(list(keywords)[:3])}",
                        }],
                        severity=0.5,
                    ))

        # Detect explicit disagreements
        for i, r1 in enumerate(responses):
            for r2 in responses[i+1:]:
                if self._has_contradiction(r1.content, r2.content):
                    disagreements.append(Disagreement(
                        topic="观点对立",
                        positions=[
                            {"provider_id": r1.provider_id, "stance": r1.content[:100]},
                            {"provider_id": r2.provider_id, "stance": r2.content[:100]},
                        ],
                        severity=0.8,
                    ))

        # Calculate overall agreement
        if agreements and not disagreements:
            overall = 0.9
        elif agreements and disagreements:
            overall = 0.5
        elif not agreements and disagreements:
            overall = 0.2
        else:
            overall = 0.6

        # Generate summary
        summary = self._generate_summary(agreements, disagreements, responses)

        return ComparisonResult(
            task_id=task_id,
            query=query,
            agreements=agreements,
            disagreements=disagreements,
            summary=summary,
            overall_agreement=overall,
        )

    def _extract_keywords(self, text: str) -> set[str]:
        """Extract meaningful keywords from text."""
        # Remove common stop words
        stop_words = {
            '的', '是', '在', '了', '和', '也', '就', '都', '而', '及',
            '与', '或', '一个', '没有', '我们', '你', '我', '他', '她',
            'the', 'is', 'and', 'or', 'but', 'in', 'on', 'at', 'to',
            'a', 'an', 'of', 'for', 'it', 'this', 'that', 'with',
        }

        # Extract words (simple split for CJK)
        words = re.findall(r'[一-鿿]{2,}|[a-zA-Z]{3,}', text)
        keywords = {w.lower() for w in words if w.lower() not in stop_words and len(w) >= 2}

        # Return top 20 keywords
        return set(list(keywords)[:20])

    def _has_contradiction(self, text1: str, text2: str) -> bool:
        """Simple contradiction detection."""
        contradictions = [
            ('推荐', '不推荐'), ('适合', '不适合'), ('应该', '不应该'),
            ('好', '不好'), ('优', '劣'), ('是', '不是'),
        ]
        t1_lower = text1[:200].lower()
        t2_lower = text2[:200].lower()

        for pos, neg in contradictions:
            if pos in t1_lower and neg in t2_lower:
                return True
            if neg in t1_lower and pos in t2_lower:
                return True
        return False

    def _generate_summary(
        self,
        agreements: list[Agreement],
        disagreements: list[Disagreement],
        responses: list[AIResponse],
    ) -> str:
        parts = []
        parts.append(f"共收到 {len(responses)} 个AI的回复。")

        if agreements:
            parts.append(f"发现 {len(agreements)} 个共识点。")
        if disagreements:
            parts.append(f"发现 {len(disagreements)} 个分歧点。")

        if agreements and not disagreements:
            parts.append("所有AI观点高度一致。")
        elif disagreements:
            parts.append("存在不同观点，建议综合考虑。")

        return " ".join(parts)
