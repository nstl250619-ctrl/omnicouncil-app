"""ResponseNormalizer — parse raw AI text into structured NormalizedResponse.

This is used by Layer 3 (ResultCollector) to standardize AI responses.
"""

from __future__ import annotations

import re

from shared.types import NormalizedResponse


class ResponseNormalizer:
    """Normalize raw AI response text into structured format.

    Handles: Markdown parsing, paragraph extraction, code block detection,
    word count, language detection.
    """

    # Code block pattern: ```language\n...\n```
    _CODE_BLOCK_RE = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)
    # Table detection: lines starting with |
    _TABLE_RE = re.compile(r"^\|.+\|$", re.MULTILINE)
    # CJK character range for language detection
    _CJK_RE = re.compile(r"[一-鿿぀-ゟ゠-ヿ]")

    def normalize(self, raw_text: str) -> NormalizedResponse:
        """Normalize raw AI response text."""
        if not raw_text or not raw_text.strip():
            return NormalizedResponse(main_text="")

        # Extract code blocks
        code_blocks: list[tuple[str, str]] = []
        for match in self._CODE_BLOCK_RE.finditer(raw_text):
            lang = match.group(1) or "text"
            code = match.group(2).strip()
            code_blocks.append((lang, code))

        # Remove code blocks from text for paragraph extraction
        text_without_code = self._CODE_BLOCK_RE.sub("", raw_text).strip()

        # Extract paragraphs
        paragraphs = self._extract_paragraphs(text_without_code)

        # Detect language
        detected_language = self._detect_language(raw_text)

        # Check for Markdown features
        has_markdown = self._has_markdown(raw_text)

        # Word count
        word_count = self.count_words(raw_text)

        return NormalizedResponse(
            main_text=raw_text.strip(),
            code_blocks=code_blocks,
            paragraphs=paragraphs,
            word_count=word_count,
            detected_language=detected_language,
            has_markdown=has_markdown,
        )

    def _extract_paragraphs(self, text: str) -> list[str]:
        """Split text into paragraphs."""
        # Split by double newline, filter empty
        raw_paragraphs = re.split(r"\n\s*\n", text)
        paragraphs = []
        for p in raw_paragraphs:
            cleaned = p.strip()
            if cleaned and len(cleaned) >= 10:  # min paragraph length
                # Normalize whitespace
                cleaned = re.sub(r"\s+", " ", cleaned)
                paragraphs.append(cleaned)
        return paragraphs

    def _detect_language(self, text: str) -> str:
        """Detect primary language (simple heuristic)."""
        cjk_count = len(self._CJK_RE.findall(text))
        total_chars = len(text.strip())
        if total_chars == 0:
            return "unknown"
        ratio = cjk_count / total_chars
        if ratio > 0.3:
            return "zh"
        return "en"

    def _has_markdown(self, text: str) -> bool:
        """Check if text contains Markdown features."""
        markdown_indicators = [
            re.compile(r"^#{1,6}\s", re.MULTILINE),      # Headers
            re.compile(r"\*\*.*?\*\*"),                     # Bold
            re.compile(r"^\s*[-*+]\s", re.MULTILINE),     # Lists
            re.compile(r"^\s*\d+\.\s", re.MULTILINE),     # Numbered lists
            re.compile(r"```"),                             # Code blocks
            re.compile(r"\[.*?\]\(.*?\)"),                  # Links
        ]
        return any(pattern.search(text) for pattern in markdown_indicators)

    def count_words(self, text: str) -> int:
        """Count words (handles CJK characters as individual words)."""
        # Count CJK characters individually
        cjk_chars = len(self._CJK_RE.findall(text))
        # Count non-CJK words
        non_cjk = self._CJK_RE.sub(" ", text)
        non_cjk_words = len(non_cjk.split())
        return cjk_chars + non_cjk_words
