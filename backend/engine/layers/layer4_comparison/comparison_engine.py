"""ComparisonEngine — 6-stage analysis pipeline."""

from __future__ import annotations

import logging
import time

from shared.config import ComparisonConfig
from shared.event_bus import EventBus
from shared.types import (
    ComparisonContext,
    RoundContext,
)

from .pipeline.comparison_assembler import ComparisonAssembler
from .pipeline.difference_analyzer import DifferenceAnalyzer
from .pipeline.semantic_unit_extractor import SemanticUnitExtractor
from .pipeline.similarity_analyzer import SimilarityAnalyzer
from .pipeline.text_preprocessor import TextPreprocessor
from .pipeline.unique_insight_extractor import UniqueInsightExtractor

logger = logging.getLogger(__name__)


class ComparisonEngine:
    """Comparison Analysis Center — 6-stage pipeline.

    RoundContext → Preprocess → Extract Units → Similarity → Differences → Unique → ComparisonContext
    """

    def __init__(
        self,
        config: ComparisonConfig | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._config = config or ComparisonConfig()
        self._event_bus = event_bus or EventBus()

        # Pipeline stages
        self._preprocessor = TextPreprocessor(self._config)
        self._unit_extractor = SemanticUnitExtractor()
        self._similarity_analyzer = SimilarityAnalyzer(self._config)
        self._difference_analyzer = DifferenceAnalyzer(self._config)
        self._unique_extractor = UniqueInsightExtractor(self._config)
        self._assembler = ComparisonAssembler()

    def analyze(self, context: RoundContext) -> ComparisonContext:
        """Run the full 6-stage analysis pipeline."""
        start = time.time()

        # Validate input
        successful = [r for r in context.results if r.status.value == "success"]
        if len(successful) < 2:
            return ComparisonContext(
                task_id=context.task_id,
                round_number=context.round_number,
                query=context.query,
                source_context_id=f"{context.task_id}_r{context.round_number}",
                generated_at=time.time(),
                degraded="single_source" if len(successful) == 1 else "no_results",
            )

        # Stage 1: Preprocess
        preprocessed = self._preprocessor.process(context)

        # Stage 2: Extract semantic units
        units = self._unit_extractor.extract(preprocessed)

        if not units:
            return ComparisonContext(
                task_id=context.task_id,
                round_number=context.round_number,
                query=context.query,
                source_context_id=f"{context.task_id}_r{context.round_number}",
                generated_at=time.time(),
                degraded="no_results",
            )

        # Stage 3: Similarity analysis
        matrix = self._similarity_analyzer.analyze(units)

        # Stage 4: Difference detection
        differences = self._difference_analyzer.detect(units, matrix)

        # Stage 5: Unique insight extraction
        unique_insights = self._unique_extractor.extract(units, matrix)

        # Stage 6: Assemble
        comparison_ctx = self._assembler.assemble(
            context, units, matrix, differences, unique_insights, self._config
        )

        elapsed = time.time() - start
        logger.info(
            "Comparison analysis completed for task %s in %.2fs: %d units, %d differences, %d unique",
            context.task_id, elapsed, len(units), len(differences), len(unique_insights),
        )

        return comparison_ctx

    def on_analysis_completed(self, callback) -> None:
        """Register callback for analysis completion."""
        self._event_bus.on("comparison:analysis:completed", callback)
