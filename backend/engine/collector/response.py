"""Unified AI response format."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AIResponse:
    """Unified response from any AI provider."""
    provider_id: str
    content: str
    response_time_ms: int = 0
    word_count: int = 0
    success: bool = True
    error: str | None = None
    metadata: dict = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
        if self.word_count == 0 and self.content:
            self.word_count = self._count_words(self.content)

    @staticmethod
    def _count_words(text: str) -> int:
        """Count words (CJK-aware)."""
        import re
        cjk = len(re.findall(r"[一-鿿぀-ゟ゠-ヿ]", text))
        non_cjk = len(re.sub(r"[一-鿿぀-ゟ゠-ヿ]", " ", text).split())
        return cjk + non_cjk

    def to_dict(self) -> dict:
        return {
            "provider_id": self.provider_id,
            "content": self.content,
            "response_time_ms": self.response_time_ms,
            "word_count": self.word_count,
            "success": self.success,
            "error": self.error,
        }
