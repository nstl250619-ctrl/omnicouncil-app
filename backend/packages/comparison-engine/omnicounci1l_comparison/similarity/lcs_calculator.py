"""Longest Common Subsequence (LCS) ratio calculator."""

from __future__ import annotations

# Guard: skip LCS for texts longer than this to avoid O(n*m) blowup
MAX_LCS_LENGTH = 500


def lcs_ratio(text_a: str, text_b: str) -> float:
    """Compute LCS length / max(len(a), len(b)).

    Uses standard DP, O(n*m) complexity.
    Falls back to 0.0 for texts exceeding MAX_LCS_LENGTH.
    """
    if not text_a or not text_b:
        return 0.0

    m, n = len(text_a), len(text_b)

    # Guard against O(n*m) blowup
    if m > MAX_LCS_LENGTH or n > MAX_LCS_LENGTH:
        # Fallback: use simple word overlap ratio
        words_a = set(text_a.split())
        words_b = set(text_b.split())
        if not words_a or not words_b:
            return 0.0
        overlap = len(words_a & words_b)
        return overlap / max(len(words_a), len(words_b))

    # Optimize: only keep two rows
    prev = [0] * (n + 1)
    curr = [0] * (n + 1)

    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if text_a[i - 1] == text_b[j - 1]:
                curr[j] = prev[j - 1] + 1
            else:
                curr[j] = max(prev[j], curr[j - 1])
        prev, curr = curr, [0] * (n + 1)

    lcs_len = prev[n]
    max_len = max(m, n)
    return lcs_len / max_len if max_len > 0 else 0.0
