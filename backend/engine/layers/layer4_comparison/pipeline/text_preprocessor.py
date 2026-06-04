"""Stage 1: TextPreprocessor — extract and clean paragraphs from RoundContext."""

from __future__ import annotations

import re
from dataclasses import dataclass

from shared.types import RoundContext, AiResult, ResultStatus
from shared.config import ComparisonConfig


@dataclass(frozen=True)
class PreprocessedAI:
    ai_id: str
    clean_paragraphs: list[str]
    original_indices: list[int]


class TextPreprocessor:
    """Clean and filter paragraphs from AI results."""

    def __init__(self, config: ComparisonConfig) -> None:
        self._min_length = config.min_paragraph_length

    def process(self, context: RoundContext) -> list[PreprocessedAI]:
        """Extract and clean paragraphs from successful AI results."""
        result = []
        for ai_result in context.results:
            if ai_result.status != ResultStatus.SUCCESS:
                continue

            clean_paragraphs = []
            original_indices = []

            for i, para in enumerate(ai_result.normalized.paragraphs):
                # Normalize whitespace
                cleaned = re.sub(r"\s+", " ", para).strip()
                # Filter short paragraphs
                if len(cleaned) >= self._min_length:
                    clean_paragraphs.append(cleaned)
                    original_indices.append(i)

            if clean_paragraphs:
                result.append(PreprocessedAI(
                    ai_id=ai_result.ai_id,
                    clean_paragraphs=clean_paragraphs,
                    original_indices=original_indices,
                ))

        return result
