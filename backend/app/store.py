"""In-memory data store, search index, audit log and analytics.

A prototype store (a dict + a TF-IDF index). In production this is PostgreSQL +
ElasticSearch, but the API surface stays identical. Holds historical seed
records plus live-triaged complaints, the officer audit trail, and computes the
supervisory analytics / clustering / NLQ used by the dashboard.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone

from . import similarity
from .schemas import AuditEntry, TriageResult
from .seed_data import seed_records
from .taxonomy import ALL_DEPARTMENTS, DISTRICTS


class Store:
    def __init__(self) -> None:
        self.records: dict[str, dict] = {}
        self.results: dict[str, TriageResult] = {}   # full AI results for live ones
        self.audit: list[AuditEntry] = []
        self.index = similarity.TfidfIndex()
        self._counter = 2000
        self._load_seed()

    def _load_seed(self) -> None:
        for rec in seed_records():
            self.records[rec["complaint_id"]] = rec
            self.index.add(rec["complaint_id"], f"{rec['category']} {rec['district']} {rec['text']}")

    # -- ids ---------------------------------------------------------------
    def next_id(self) -> str:
        self._counter += 1
        return f"JS-{self._counter}"

    # -- writes ------------------------------------------------------------
    def add_result(self, result: TriageResult) -> None:
        self.results[result.complaint_id] = result
        rec = {
            "complaint_id": result.complaint_id,
            "text": result.original_text,
            "district": result.district,
            "category": result.analysis.category,
            "department": result.analysis.department,
            "urgency": result.analysis.urgency.value,
            "status": "Open",
            "summary": result.analysis.summary,
            "created_at": result.created_at,
            "source": "live",
            "is_safety_critical": result.analysis.is_safety_critical,
        }
        self.records[result.complaint_id] = rec
        self.index.add(result.complaint_id, f"{rec['category']} {rec['district']} {rec['text']}")

    def log_decision(self, entry: AuditEntry) -> None:
        self.audit.append(entry)
        rec = self.records.get(entry.complaint_id)
        if rec:
            rec["status"] = "Routed" if entry.action in ("accept", "override") else rec.get("status", "Open")
            rec["category"] = entry.final_category
            rec["department"] = entry.final_department
            rec["urgency"] = entry.final_urgency

    # -- reads -------------------------------------------------------------
    def queue(self, limit: int = 100) -> list[dict]:
        rows = sorted(self.records.values(), key=lambda r: r.get("created_at", ""), reverse=True)
        # Surface live + open items first, criticals on top.
        urg_rank = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
        rows.sort(key=lambda r: (urg_rank.get(r.get("urgency", "Medium"), 2)))
        return rows[:limit]

    def get_result(self, cid: str) -> TriageResult | None:
        return self.results.get(cid)

    # -- analytics ---------------------------------------------------------
    def analytics(self) -> dict:
        recs = list(self.records.values())
        total = len(recs)
        by_dept = Counter(r.get("department", "Unknown") for r in recs)
        by_district = Counter(r.get("district", "Unknown") for r in recs)
        by_urgency = Counter(r.get("urgency", "Medium") for r in recs)
        by_status = Counter(r.get("status", "Open") for r in recs)
        by_category = Counter(r.get("category", "Unknown") for r in recs)
        safety = sum(1 for r in recs if r.get("is_safety_critical"))
        overrides = sum(1 for a in self.audit if a.action == "override")
        decisions = len(self.audit)
        return {
            "total_complaints": total,
            "safety_critical": safety,
            "open": by_status.get("Open", 0),
            "in_progress": by_status.get("In Progress", 0),
            "resolved": by_status.get("Resolved", 0) + by_status.get("Routed", 0),
            "ai_decisions_reviewed": decisions,
            "override_rate": round(overrides / decisions, 3) if decisions else 0.0,
            "by_department": by_dept.most_common(),
            "by_district": by_district.most_common(),
            "by_urgency": [(k, by_urgency.get(k, 0)) for k in ("Critical", "High", "Medium", "Low")],
            "by_status": by_status.most_common(),
            "top_categories": by_category.most_common(6),
        }

    def clusters(self) -> list[dict]:
        return similarity.cluster(list(self.records.values()))

    # -- Natural-language query (supervisory) ------------------------------
    def nlq(self, question: str) -> dict:
        """Lightweight, transparent NLQ: parse intent + filters from the
        question and answer over the structured store. No black box — the
        applied filters are returned so the supervisor sees exactly what ran.
        """
        q = question.lower()
        recs = list(self.records.values())
        filters: list[str] = []

        # district filter
        for d in DISTRICTS:
            if d.lower() in q:
                recs = [r for r in recs if r.get("district") == d]
                filters.append(f"district = {d}")
                break

        # department / topic keyword filter
        topic_map = {
            "water": "Water", "paani": "Water", "bijli": "Power", "power": "Power",
            "electric": "Power", "transformer": "Power", "road": "Roads", "sadak": "Roads",
            "pension": "Social Justice", "ration": "Food", "police": "Police",
            "patwari": "Revenue", "land": "Revenue", "garbage": "Municipal", "health": "Health",
            "school": "Education", "teacher": "Education", "sewer": "Water", "drain": "Water",
        }
        for kw, deptword in topic_map.items():
            if kw in q:
                recs = [r for r in recs if deptword.lower() in r.get("department", "").lower()
                        or deptword.lower() in r.get("category", "").lower()]
                filters.append(f"topic ~ {deptword}")
                break

        # urgency filter
        for u in ("critical", "high", "medium", "low"):
            if u in q:
                recs = [r for r in recs if r.get("urgency", "").lower() == u]
                filters.append(f"urgency = {u.title()}")
                break
        if "urgent" in q or "safety" in q:
            recs = [r for r in recs if r.get("urgency") == "Critical" or r.get("is_safety_critical")]
            filters.append("urgent / safety-critical")

        # status filter
        if "pending" in q or "open" in q or "unresolved" in q:
            recs = [r for r in recs if r.get("status") in ("Open", "In Progress")]
            filters.append("status = Open/In Progress")
        if "resolved" in q or "closed" in q:
            recs = [r for r in recs if r.get("status") in ("Resolved", "Routed")]
            filters.append("status = Resolved")

        # "delay/old" → simple age intent (days since created)
        if "delay" in q or "old" in q or "long pending" in q:
            def age_days(r):
                try:
                    return (datetime.now(timezone.utc) - datetime.fromisoformat(r["created_at"])).days
                except Exception:
                    return 0
            recs = [r for r in recs if age_days(r) >= 7 and r.get("status") in ("Open", "In Progress")]
            filters.append("pending ≥ 7 days")

        rows = sorted(recs, key=lambda r: r.get("created_at", ""), reverse=True)[:50]
        return {
            "question": question,
            "applied_filters": filters or ["no filters matched — showing recent complaints"],
            "count": len(recs),
            "results": [
                {
                    "complaint_id": r["complaint_id"],
                    "summary": r.get("summary", r.get("text", ""))[:120],
                    "district": r.get("district"),
                    "department": r.get("department"),
                    "category": r.get("category"),
                    "urgency": r.get("urgency"),
                    "status": r.get("status"),
                }
                for r in rows[:25]
            ],
        }


store = Store()
