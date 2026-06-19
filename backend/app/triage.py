"""Triage orchestration — ties preprocessing, the LLM provider, the
deterministic safety floor, SLA/routing and RAG retrieval into one result.

Key design point: the LLM is advisory, but a DETERMINISTIC, department-validated
safety rule can only ever *raise* urgency, never lower it. So a complaint
mentioning a sparking transformer is guaranteed Critical even if the model
under-rates it. This is the "rules + historical patterns" combination the brief
asks for, and it is fully auditable.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from .preprocess import detect_script, normalize
from .schemas import SimilarCase, TriageAnalysis, TriageResult, UrgencyLevel
from .taxonomy import (
    SAFETY_CRITICAL_SIGNALS,
    VULNERABILITY_SIGNALS,
    routing_for_category,
    sla_for_category,
)

_URGENCY_RANK = {
    UrgencyLevel.LOW: 0,
    UrgencyLevel.MEDIUM: 1,
    UrgencyLevel.HIGH: 2,
    UrgencyLevel.CRITICAL: 3,
}
_RANK_URGENCY = {v: k for k, v in _URGENCY_RANK.items()}


def _apply_safety_floor(text: str, analysis: TriageAnalysis) -> TriageAnalysis:
    low = text.lower()
    hit_safety = [s for s in SAFETY_CRITICAL_SIGNALS if s.lower() in low]
    hit_vuln = [s for s in VULNERABILITY_SIGNALS if s.lower() in low]

    if hit_safety:
        if _URGENCY_RANK[analysis.urgency] < _URGENCY_RANK[UrgencyLevel.CRITICAL]:
            analysis.urgency = UrgencyLevel.CRITICAL
            analysis.confidence.urgency = max(analysis.confidence.urgency, 0.95)
            analysis.reason_codes.append(
                f"SAFETY RULE: critical signal(s) detected → urgency floored to Critical [{', '.join(sorted(set(hit_safety))[:3])}]"
            )
        analysis.is_safety_critical = True
    elif hit_vuln and _URGENCY_RANK[analysis.urgency] < _URGENCY_RANK[UrgencyLevel.HIGH]:
        analysis.urgency = UrgencyLevel.HIGH
        analysis.reason_codes.append(
            f"PRIORITY RULE: vulnerable-group signal → urgency raised to High [{', '.join(sorted(set(hit_vuln))[:2])}]"
        )
    return analysis


def triage(
    provider,
    index,
    records_by_id: dict,
    text: str,
    district: str,
    complaint_id: str,
) -> TriageResult:
    normalized, notes = normalize(text)
    lang_hint = detect_script(text)

    # Run the LLM classification and the complaint's embedding CONCURRENTLY.
    # The embedding (used for similarity + stored on save) overlaps with the
    # slower LLM call instead of running after it, cutting end-to-end latency.
    def _prewarm_embedding():
        embed_one = getattr(index, "_embed_one", None)
        if embed_one:
            try:
                embed_one(text)  # caches the vector for similar() + save reuse
            except Exception:
                pass

    with ThreadPoolExecutor(max_workers=2) as pool:
        analysis_future = pool.submit(provider.analyze, normalized, lang_hint, notes)
        pool.submit(_prewarm_embedding)
        analysis = analysis_future.result()

    analysis = _apply_safety_floor(normalized, analysis)

    # Prepend the preprocessing notes so the officer sees what was expanded.
    for n in reversed(notes):
        if n not in analysis.reason_codes:
            analysis.reason_codes.insert(0, n)

    sla_days = sla_for_category(analysis.category)
    # Critical cases get a compressed SLA.
    if analysis.urgency == UrgencyLevel.CRITICAL:
        sla_days = min(sla_days, 1)
    elif analysis.urgency == UrgencyLevel.HIGH:
        sla_days = max(1, sla_days // 2)

    now = datetime.now(timezone.utc)
    due = now + timedelta(days=sla_days)

    # RAG: retrieve similar past complaints for officer context + duplicate flag.
    similar: list[SimilarCase] = []
    is_dup = False
    dup_threshold = getattr(index, "dup_threshold", 0.55)
    # Query by the raw complaint text — already embedded above (cache hit), and
    # identical to what the store will embed on save (another cache hit).
    for doc_id, score in index.similar(text, top_k=3, exclude=complaint_id):
        rec = records_by_id.get(doc_id)
        if not rec:
            continue
        similar.append(SimilarCase(
            complaint_id=doc_id,
            summary=rec.get("summary", rec.get("text", ""))[:140],
            category=rec.get("category", ""),
            district=rec.get("district", ""),
            similarity=score,
            status=rec.get("status", "Open"),
        ))
        if score >= dup_threshold and rec.get("district") == district:
            is_dup = True

    return TriageResult(
        complaint_id=complaint_id,
        original_text=text,
        normalized_text=normalized,
        district=district,
        analysis=analysis,
        routing_office=f"{routing_for_category(analysis.category)} — {district}",
        suggested_sla_days=sla_days,
        sla_due=due.isoformat(),
        similar_cases=similar,
        is_potential_duplicate=is_dup,
        provider=provider.name,
        created_at=now.isoformat(),
    )
