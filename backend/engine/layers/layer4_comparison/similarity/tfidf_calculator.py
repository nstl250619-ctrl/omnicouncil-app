"""TF-IDF calculator using bigram tokenization (zero dependency)."""

from __future__ import annotations

import math
import re
from collections import Counter


class TfidfCalculator:
    """Compute TF-IDF vectors for text documents using bigram tokenization.

    Bigram approach: split text into overlapping 2-character sequences.
    This works well for Chinese text without any external dependency.
    """

    def __init__(self) -> None:
        self._vocabulary: dict[str, int] = {}
        self._idf: dict[str, float] = {}

    def fit_transform(self, documents: list[str]) -> list[dict[str, float]]:
        """Build vocabulary and compute TF-IDF vectors for all documents."""
        # Tokenize all documents into bigrams
        tokenized = [self._tokenize(doc) for doc in documents]

        # Build vocabulary
        all_terms = set()
        for tokens in tokenized:
            all_terms.update(tokens)
        self._vocabulary = {term: i for i, term in enumerate(sorted(all_terms))}

        # Compute IDF
        n_docs = len(documents)
        doc_freq = Counter()
        for tokens in tokenized:
            unique_terms = set(tokens)
            for term in unique_terms:
                doc_freq[term] += 1

        self._idf = {
            term: math.log((n_docs + 1) / (freq + 1)) + 1
            for term, freq in doc_freq.items()
        }

        # Compute TF-IDF for each document
        vectors = []
        for tokens in tokenized:
            tf = Counter(tokens)
            total = len(tokens) if tokens else 1
            tfidf = {}
            for term, count in tf.items():
                tfidf[term] = (count / total) * self._idf.get(term, 1.0)
            vectors.append(tfidf)

        return vectors

    def _tokenize(self, text: str) -> list[str]:
        """Tokenize text into bigrams.

        For Chinese: character-level bigrams.
        For English: word-level (split by space).
        """
        # Check if text is primarily CJK
        cjk_count = sum(1 for c in text if "一" <= c <= "鿿")
        if cjk_count / max(len(text), 1) > 0.3:
            return self._bigram_tokenize(text)
        else:
            return self._word_tokenize(text)

    def _bigram_tokenize(self, text: str) -> list[str]:
        """Character-level bigram tokenization for CJK text."""
        # Remove whitespace and punctuation
        cleaned = ""
        for c in text:
            if "一" <= c <= "鿿" or c.isalnum():
                cleaned += c
        if len(cleaned) < 2:
            return [cleaned] if cleaned else []
        return [cleaned[i : i + 2] for i in range(len(cleaned) - 1)]

    def _word_tokenize(self, text: str) -> list[str]:
        """Word-level tokenization for non-CJK text."""
        words = re.findall(r"\w+", text.lower())
        return words if words else []
