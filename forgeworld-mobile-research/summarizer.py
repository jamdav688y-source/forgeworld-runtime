"""Deterministic, local, extractive summarizer.

No cloud calls, no language model. Summaries are always labeled
SYSTEM_EXTRACTIVE_SUMMARY so they are never mistaken for model-generated
understanding or verified fact.
"""
from __future__ import annotations

import re
from collections import Counter

SUMMARY_LABEL = "SYSTEM_EXTRACTIVE_SUMMARY"

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "is", "are", "was", "were", "be",
    "been", "being", "to", "of", "in", "on", "for", "with", "as", "by",
    "at", "from", "that", "this", "it", "its", "into", "your", "you",
    "we", "i", "he", "she", "they", "them", "his", "her", "their", "our",
    "if", "then", "so", "not", "no", "yes", "will", "would", "can", "could",
    "should", "have", "has", "had", "do", "does", "did", "up", "down",
}

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_\-]{2,}")


def _split_sentences(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []
    parts = re.split(r"(?<=[.!?])\s+", normalized)
    return [p.strip() for p in parts if p.strip()]


def _term_frequencies(text: str) -> Counter:
    words = [w.lower() for w in _WORD_RE.findall(text)]
    words = [w for w in words if w not in _STOPWORDS]
    return Counter(words)


def extractive_summary(text: str, max_sentences: int = 3, max_chars: int = 600) -> str:
    """Build a short extractive summary from OCR/derived text.

    Selects the highest-information sentences (by term frequency) while
    preferring earlier sentences (likely titles/headers) as tie-breakers.
    Returns an empty string when there is no usable text.
    """
    if not text or not text.strip():
        return ""

    sentences = _split_sentences(text)
    if not sentences:
        return ""

    if len(sentences) <= max_sentences:
        chosen = sentences
    else:
        freqs = _term_frequencies(text)
        scored = []
        for idx, sentence in enumerate(sentences):
            words = [w.lower() for w in _WORD_RE.findall(sentence)]
            score = sum(freqs.get(w, 0) for w in words)
            position_bonus = 1.0 if idx == 0 else 0.0
            scored.append((score + position_bonus, idx, sentence))
        top = sorted(scored, key=lambda t: (-t[0], t[1]))[:max_sentences]
        chosen = [s for _, _, s in sorted(top, key=lambda t: t[1])]

    summary = " ".join(chosen)
    if len(summary) > max_chars:
        summary = summary[:max_chars].rsplit(" ", 1)[0] + "..."
    return summary


def build_labeled_summary(text: str, max_sentences: int = 3, max_chars: int = 600) -> str:
    body = extractive_summary(text, max_sentences=max_sentences, max_chars=max_chars)
    if not body:
        return ""
    return f"[{SUMMARY_LABEL}] {body}"
