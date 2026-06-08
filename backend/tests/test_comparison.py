"""Unit tests for engine/layers/layer4_comparison/ pipeline."""

from __future__ import annotations

import time


from shared.config import ComparisonConfig
from shared.types import (
    AiResult,
    NormalizedResponse,
    ResultStatus,
    RoundContext,
    RoundContextSummary,
    TaskMode,
)
from omnicounci1l_comparison import ComparisonEngine
from omnicounci1l_comparison.pipeline.text_preprocessor import TextPreprocessor
from omnicounci1l_comparison.pipeline.semantic_unit_extractor import SemanticUnitExtractor
from omnicounci1l_comparison.pipeline.similarity_analyzer import SimilarityAnalyzer
from omnicounci1l_comparison.pipeline.difference_analyzer import DifferenceAnalyzer
from omnicounci1l_comparison.pipeline.unique_insight_extractor import UniqueInsightExtractor
from omnicounci1l_comparison.pipeline.comparison_assembler import ComparisonAssembler


def make_round_ctx(ai_texts=None):
    if ai_texts is None:
        ai_texts = {
            "deepseek": "量子计算利用量子比特进行计算，与经典计算不同。",
            "qianwen": "量子计算基于量子力学原理，使用量子比特处理信息。",
        }
    results = []
    for ai_id, text in ai_texts.items():
        results.append(AiResult(
            ai_id=ai_id, task_id="t1", round_number=1,
            status=ResultStatus.SUCCESS, raw_text=text,
            normalized=NormalizedResponse(
                main_text=text,
                paragraphs=[text],
                word_count=len(text),
            ),
            duration=1.0,
        ))
    return RoundContext(
        task_id="t1", round_number=1, query="什么是量子计算",
        execution_mode=TaskMode.PARALLEL, results=results,
        summary=RoundContextSummary(total_ais=len(results), success_count=len(results)),
        created_at=time.time(),
    )


class TestTextPreprocessor:
    def test_process(self):
        config = ComparisonConfig()
        preprocessor = TextPreprocessor(config)
        ctx = make_round_ctx()
        result = preprocessor.process(ctx)
        assert len(result) == 2
        assert result[0].ai_id == "deepseek"
        assert len(result[0].clean_paragraphs) > 0

    def test_filters_short_paragraphs(self):
        config = ComparisonConfig(min_paragraph_length=100)
        preprocessor = TextPreprocessor(config)
        ctx = make_round_ctx()
        result = preprocessor.process(ctx)
        # Short paragraphs should be filtered
        for ai in result:
            for p in ai.clean_paragraphs:
                assert len(p) >= 100

    def test_skips_failed_results(self):
        config = ComparisonConfig()
        preprocessor = TextPreprocessor(config)
        ctx = make_round_ctx()
        # Add a failed result
        ctx.results.append(AiResult(
            ai_id="gemini", task_id="t1", round_number=1,
            status=ResultStatus.ERROR, raw_text="",
            normalized=NormalizedResponse(main_text=""),
        ))
        result = preprocessor.process(ctx)
        assert len(result) == 2  # Only successful results


class TestSemanticUnitExtractor:
    def test_extract(self):
        extractor = SemanticUnitExtractor()
        preprocessed = [
            type("PreprocessedAI", (), {
                "ai_id": "deepseek",
                "clean_paragraphs": ["paragraph 1", "paragraph 2"],
                "original_indices": [0, 1],
            })(),
        ]
        units = extractor.extract(preprocessed)
        assert len(units) == 2
        assert units[0].source_ai_id == "deepseek"

    def test_max_units_per_ai(self):
        extractor = SemanticUnitExtractor(max_units_per_ai=2)
        preprocessed = [
            type("PreprocessedAI", (), {
                "ai_id": "deepseek",
                "clean_paragraphs": ["p1", "p2", "p3", "p4", "p5"],
                "original_indices": [0, 1, 2, 3, 4],
            })(),
        ]
        units = extractor.extract(preprocessed)
        assert len(units) == 2


class TestSimilarityAnalyzer:
    def test_analyze(self):
        config = ComparisonConfig()
        analyzer = SimilarityAnalyzer(config)
        from shared.types import SemanticUnit
        units = [
            SemanticUnit(unit_id="u1", source_ai_id="a", content="quantum computing uses qubits"),
            SemanticUnit(unit_id="u2", source_ai_id="b", content="quantum computing leverages qubits"),
        ]
        matrix = analyzer.analyze(units)
        assert len(matrix.ai_ids) == 2
        assert matrix.pairwise_similarities[0][1] > 0

    def test_analyze_empty(self):
        config = ComparisonConfig()
        analyzer = SimilarityAnalyzer(config)
        matrix = analyzer.analyze([])
        assert matrix.ai_ids == []


class TestDifferenceAnalyzer:
    def test_detect(self):
        config = ComparisonConfig()
        analyzer = DifferenceAnalyzer(config)
        from shared.types import SemanticUnit, SimilarityMatrix
        units = [
            SemanticUnit(unit_id="u1", source_ai_id="a", content="quantum is good"),
            SemanticUnit(unit_id="u2", source_ai_id="b", content="quantum is bad"),
        ]
        matrix = SimilarityMatrix(
            ai_ids=["a", "b"],
            pairwise_similarities=[[1.0, 0.2], [0.2, 1.0]],
            unit_matrix=[[1.0, 0.2], [0.2, 1.0]],
            unit_index=["u1", "u2"],
        )
        differences = analyzer.detect(units, matrix)
        assert isinstance(differences, list)


class TestUniqueInsightExtractor:
    def test_extract(self):
        config = ComparisonConfig()
        extractor = UniqueInsightExtractor(config)
        from shared.types import SemanticUnit, SimilarityMatrix
        units = [
            SemanticUnit(unit_id="u1", source_ai_id="a", content="unique insight from a"),
            SemanticUnit(unit_id="u2", source_ai_id="b", content="common view"),
        ]
        matrix = SimilarityMatrix(
            ai_ids=["a", "b"],
            pairwise_similarities=[[1.0, 0.1], [0.1, 1.0]],
            unit_matrix=[[1.0, 0.1], [0.1, 1.0]],
            unit_index=["u1", "u2"],
        )
        insights = extractor.extract(units, matrix)
        assert isinstance(insights, list)


class TestComparisonAssembler:
    def test_assemble(self):
        assembler = ComparisonAssembler()
        ctx = make_round_ctx()
        from shared.types import SemanticUnit, SimilarityMatrix
        units = [
            SemanticUnit(unit_id="u1", source_ai_id="deepseek", content="test"),
        ]
        matrix = SimilarityMatrix(ai_ids=["deepseek"])
        result = assembler.assemble(ctx, units, matrix, [], [], ComparisonConfig())
        assert result.task_id == "t1"
        assert result.metrics.total_units == 1


class TestComparisonEngine:
    def test_analyze(self):
        config = ComparisonConfig()
        engine = ComparisonEngine(config=config)
        ctx = make_round_ctx()
        result = engine.analyze(ctx)
        assert result.task_id == "t1"
        assert result.degraded is None

    def test_analyze_single_source(self):
        config = ComparisonConfig()
        engine = ComparisonEngine(config=config)
        ctx = make_round_ctx(ai_texts={"deepseek": "only one response"})
        result = engine.analyze(ctx)
        assert result.degraded == "single_source"

    def test_analyze_no_results(self):
        config = ComparisonConfig()
        engine = ComparisonEngine(config=config)
        ctx = RoundContext(
            task_id="t1", round_number=1, query="q",
            execution_mode=TaskMode.PARALLEL, results=[],
            summary=RoundContextSummary(), created_at=time.time(),
        )
        result = engine.analyze(ctx)
        assert result.degraded == "no_results"
