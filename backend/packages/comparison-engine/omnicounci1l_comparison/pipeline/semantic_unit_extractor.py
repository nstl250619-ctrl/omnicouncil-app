"""Stage 2: SemanticUnitExtractor — convert paragraphs to SemanticUnit objects."""

from __future__ import annotations

from typing import TYPE_CHECKING

from omnicounci1l_core.types import SemanticUnit, generate_id

if TYPE_CHECKING:
    from .text_preprocessor import PreprocessedAI

DEFAULT_MAX_UNITS_PER_AI = 100


class SemanticUnitExtractor:
    """Convert preprocessed paragraphs into SemanticUnit IR."""

    def __init__(self, max_units_per_ai: int = DEFAULT_MAX_UNITS_PER_AI) -> None:
        self._max_units_per_ai = max_units_per_ai

    def extract(self, preprocessed: list[PreprocessedAI]) -> list[SemanticUnit]:
        """Create SemanticUnit from each paragraph, capped per AI."""
        units = []
        for ai in preprocessed:
            for i, paragraph in enumerate(ai.clean_paragraphs[:self._max_units_per_ai]):
                units.append(SemanticUnit(
                    unit_id=generate_id("unit"),
                    source_ai_id=ai.ai_id,
                    content=paragraph,
                    paragraph_index=ai.original_indices[i],
                    unit_type="paragraph",
                ))
        return units
