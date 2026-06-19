"""Dependency-light semantic similarity, duplicate detection and clustering.

The prototype uses a pure-Python TF-IDF + cosine engine so it runs offline on
low-end hardware with zero model downloads (the brief's "low-resource
readiness" criterion). The PRODUCTION engine swaps this for IndicBERT / MuRIL
sentence embeddings behind the same two functions — see ARCHITECTURE.md.

Used for three things the brief asks for:
  * "group similar complaints" (clustering for supervisory review)
  * "duplicate complaint detection"
  * retrieval of similar past cases (the RAG context shown to officers)
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict

_TOKEN_RE = re.compile(r"[A-Za-zऀ-ॿ]+")

# Very common words (EN + transliterated HI) that add noise to similarity.
_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "in", "on", "of", "to", "and", "for",
    "my", "no", "not", "there", "this", "that", "ka", "ki", "ke", "me", "mein",
    "hai", "ho", "se", "ne", "par", "aur", "ko", "nahi", "kar", "raha", "rahe",
}


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text) if t.lower() not in _STOPWORDS and len(t) > 1]


class TfidfIndex:
    """Tiny incremental TF-IDF index with cosine similarity (offline fallback)."""

    # Cosine thresholds tuned for sparse TF-IDF vectors (lower than embeddings).
    cluster_threshold = 0.18
    dup_threshold = 0.55

    def __init__(self) -> None:
        self._docs: dict[str, Counter] = {}
        self._df: Counter = Counter()
        self._norm: dict[str, float] = {}
        self._dirty = True

    def add(self, doc_id: str, text: str) -> None:
        tokens = tokenize(text)
        tf = Counter(tokens)
        self._docs[doc_id] = tf
        for term in tf:
            self._df[term] += 1
        self._dirty = True

    def add_many(self, items: list[tuple[str, str]]) -> None:
        for doc_id, text in items:
            self.add(doc_id, text)

    def _idf(self, term: str) -> float:
        n = len(self._docs)
        return math.log((1 + n) / (1 + self._df.get(term, 0))) + 1.0

    def _vector(self, tf: Counter) -> dict[str, float]:
        return {term: freq * self._idf(term) for term, freq in tf.items()}

    def _ensure_norms(self) -> None:
        if not self._dirty:
            return
        self._norm = {}
        for doc_id, tf in self._docs.items():
            vec = self._vector(tf)
            self._norm[doc_id] = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        self._dirty = False

    def similar(self, text: str, top_k: int = 3, exclude: str | None = None) -> list[tuple[str, float]]:
        self._ensure_norms()
        q_tf = Counter(tokenize(text))
        q_vec = self._vector(q_tf)
        q_norm = math.sqrt(sum(v * v for v in q_vec.values())) or 1.0
        scored: list[tuple[str, float]] = []
        for doc_id, tf in self._docs.items():
            if doc_id == exclude:
                continue
            d_vec = self._vector(tf)
            dot = sum(q_vec.get(t, 0.0) * w for t, w in d_vec.items())
            sim = dot / (q_norm * self._norm[doc_id])
            if sim > 0:
                scored.append((doc_id, round(sim, 4)))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def pairwise_similarity(self, a: str, b: str) -> float:
        """Cosine similarity between two doc_ids already in the index."""
        self._ensure_norms()
        if a not in self._docs or b not in self._docs:
            return 0.0
        va, vb = self._vector(self._docs[a]), self._vector(self._docs[b])
        dot = sum(va.get(t, 0.0) * w for t, w in vb.items())
        return round(dot / (self._norm[a] * self._norm[b]), 4)


def cluster(records: list[dict], index, threshold: float | None = None) -> list[dict]:
    """Greedy single-link clustering for supervisory 'systemic issue' detection.

    Uses the live store index (TF-IDF offline, or Gemini semantic embeddings
    when available) — so it groups complaints by *meaning*, not just shared
    words. `records` are dicts with at least: complaint_id, summary, category,
    department, district, status, text. Clusters surface recurring issues
    (same problem, same area) so supervisors can spot bottlenecks early.
    """
    if threshold is None:
        threshold = getattr(index, "cluster_threshold", 0.18)

    unassigned = {r["complaint_id"]: r for r in records}
    clusters: list[list[dict]] = []

    while unassigned:
        seed_id, seed = next(iter(unassigned.items()))
        group = [seed]
        del unassigned[seed_id]
        for other_id in list(unassigned):
            sim = index.pairwise_similarity(seed_id, other_id)
            same_area = unassigned[other_id].get("district") == seed.get("district")
            same_dept = unassigned[other_id].get("department") == seed.get("department")
            # Cluster when textually similar AND (same area or same department)
            if sim >= threshold and (same_area or same_dept):
                group.append(unassigned[other_id])
                del unassigned[other_id]
        if len(group) >= 2:
            clusters.append(group)

    out = []
    for i, group in enumerate(sorted(clusters, key=len, reverse=True)):
        districts = sorted({g.get("district", "") for g in group})
        depts = sorted({g.get("department", "") for g in group})
        out.append({
            "cluster_id": f"CL-{i+1:03d}",
            "size": len(group),
            "label": group[0].get("category", "Issue"),
            "districts": districts,
            "departments": depts,
            "complaint_ids": [g["complaint_id"] for g in group],
            "samples": [g.get("summary", g.get("text", ""))[:140] for g in group[:4]],
            "is_systemic": len(group) >= 3,
            # Full per-complaint rows so the UI can expand a cluster on click.
            "complaints": [
                {
                    "complaint_id": g["complaint_id"],
                    "summary": (g.get("summary") or g.get("text", ""))[:160],
                    "district": g.get("district", ""),
                    "department": g.get("department", ""),
                    "category": g.get("category", ""),
                    "urgency": g.get("urgency", "Medium"),
                    "status": g.get("status", "Open"),
                }
                for g in group
            ],
        })
    return out
