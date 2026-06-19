"""Gemini-embedding-backed semantic index.

Drop-in replacement for the offline TF-IDF index (same method surface:
add / add_many / similar / pairwise_similarity), but similarity is computed over
Gemini semantic embeddings instead of bag-of-words TF-IDF — so "paani nahi aa
raha" and "no water supply" land close together even with no shared tokens.

Falls back to the TF-IDF index automatically if Gemini embeddings are
unavailable, so the system never hard-fails.
"""

from __future__ import annotations

import math

from . import gemini
from .similarity import TfidfIndex


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


class EmbeddingIndex:
    # Cosine thresholds tuned for semantic embeddings (higher than TF-IDF).
    cluster_threshold = 0.74
    dup_threshold = 0.86

    def __init__(self) -> None:
        self._vecs: dict[str, list[float]] = {}
        self._cache: dict[str, list[float]] = {}

    # -- internal embedding with cache ------------------------------------
    def _embed_one(self, text: str) -> list[float]:
        if text not in self._cache:
            self._cache[text] = gemini.embed(text)
        return self._cache[text]

    # -- writes ------------------------------------------------------------
    def add(self, doc_id: str, text: str) -> None:
        try:
            self._vecs[doc_id] = self._embed_one(text)
        except Exception:
            # Throttled / offline: skip indexing this record rather than crash.
            pass

    def add_many(self, items: list[tuple[str, str]]) -> None:
        """Batch-embed (doc_id, text) pairs in one API call."""
        texts = [t for _, t in items]
        vectors = gemini.embed_batch(texts)
        for (doc_id, text), vec in zip(items, vectors):
            self._vecs[doc_id] = vec
            self._cache[text] = vec

    # -- reads -------------------------------------------------------------
    def similar(self, text: str, top_k: int = 3, exclude: str | None = None) -> list[tuple[str, float]]:
        try:
            q = self._embed_one(text)
        except Exception:
            return []  # throttled / offline → no similar cases rather than error
        scored = [
            (doc_id, round(_cosine(q, v), 4))
            for doc_id, v in self._vecs.items()
            if doc_id != exclude
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def pairwise_similarity(self, a: str, b: str) -> float:
        if a not in self._vecs or b not in self._vecs:
            return 0.0
        return round(_cosine(self._vecs[a], self._vecs[b]), 4)


def make_index():
    """Return a semantic Gemini index when available, else the offline TF-IDF
    index. Probes Gemini once so a missing key / no network degrades cleanly."""
    if gemini.is_available():
        try:
            gemini.embed("healthcheck")
            return EmbeddingIndex()
        except Exception:
            pass
    return TfidfIndex()
