"""Data store with optional PostgreSQL persistence.

In-memory dicts + TF-IDF/embedding index remain the primary read path (fast,
supports semantic search). PostgreSQL (when DATABASE_URL is set) is the
persistence layer: every write is mirrored to the DB and the full state is
reloaded from DB on startup.

Falls back to pure in-memory mode if DATABASE_URL is not set.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from . import database, embeddings, gemini, similarity
from .database import AuditRow, ComplaintRow
from .schemas import AuditEntry, TriageResult
from .seed_data import seed_records
from .taxonomy import ALL_DEPARTMENTS, DISTRICTS


class Store:
    def __init__(self) -> None:
        self.records: dict[str, dict] = {}
        self.results: dict[str, TriageResult] = {}
        self.audit: list[AuditEntry] = []
        self.index = embeddings.make_index()
        self._counter = 2000
        self._use_db = database.init_db()
        if self._use_db:
            self._load_from_db()
        else:
            self._load_seed()

    def _index_text(self, rec: dict) -> str:
        return rec.get("text", "")

    # ------------------------------------------------------------------
    # Startup loaders
    # ------------------------------------------------------------------

    def _load_from_db(self) -> None:
        with database.session() as db:
            if db.query(ComplaintRow).count() == 0:
                for rec in seed_records():
                    db.add(ComplaintRow(
                        complaint_id=rec["complaint_id"],
                        text=rec["text"],
                        district=rec["district"],
                        category=rec["category"],
                        department=rec["department"],
                        urgency=rec["urgency"],
                        status=rec["status"],
                        summary=rec["summary"],
                        created_at=rec["created_at"],
                        source=rec["source"],
                        is_safety_critical=False,
                        triage_json=None,
                    ))

            for row in db.query(ComplaintRow).all():
                rec = {
                    "complaint_id": row.complaint_id,
                    "text": row.text,
                    "district": row.district,
                    "category": row.category,
                    "department": row.department,
                    "urgency": row.urgency,
                    "status": row.status,
                    "summary": row.summary,
                    "created_at": row.created_at,
                    "source": row.source,
                    "is_safety_critical": row.is_safety_critical,
                }
                self.records[row.complaint_id] = rec
                if row.triage_json:
                    try:
                        self.results[row.complaint_id] = TriageResult(**row.triage_json)
                    except Exception:
                        pass

            for ar in db.query(AuditRow).all():
                self.audit.append(AuditEntry(
                    complaint_id=ar.complaint_id,
                    officer_id=ar.officer_id,
                    action=ar.action,
                    ai_category=ar.ai_category,
                    final_category=ar.final_category,
                    ai_department=ar.ai_department,
                    final_department=ar.final_department,
                    ai_urgency=ar.ai_urgency,
                    final_urgency=ar.final_urgency,
                    reason=ar.reason,
                    timestamp=ar.timestamp,
                ))

        self.index.add_many([(cid, self._index_text(rec)) for cid, rec in self.records.items()])

        numeric_ids = [int(cid[3:]) for cid in self.records if cid.startswith("JS-") and cid[3:].isdigit()]
        if numeric_ids:
            self._counter = max(numeric_ids)

    def _load_seed(self) -> None:
        records = seed_records()
        for rec in records:
            self.records[rec["complaint_id"]] = rec
        self.index.add_many([(r["complaint_id"], self._index_text(r)) for r in records])

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
        self.index.add(result.complaint_id, self._index_text(rec))

        if self._use_db:
            with database.session() as db:
                db.merge(ComplaintRow(
                    complaint_id=rec["complaint_id"],
                    text=rec["text"],
                    district=rec["district"],
                    category=rec["category"],
                    department=rec["department"],
                    urgency=rec["urgency"],
                    status=rec["status"],
                    summary=rec["summary"],
                    created_at=rec["created_at"],
                    source=rec["source"],
                    is_safety_critical=rec["is_safety_critical"],
                    triage_json=result.model_dump(),
                ))

    def log_decision(self, entry: AuditEntry) -> None:
        self.audit.append(entry)
        rec = self.records.get(entry.complaint_id)
        if rec:
            rec["status"] = "Routed" if entry.action in ("accept", "override") else rec.get("status", "Open")
            rec["category"] = entry.final_category
            rec["department"] = entry.final_department
            rec["urgency"] = entry.final_urgency

        if self._use_db:
            with database.session() as db:
                db.add(AuditRow(
                    complaint_id=entry.complaint_id,
                    officer_id=entry.officer_id,
                    action=entry.action,
                    ai_category=entry.ai_category,
                    final_category=entry.final_category,
                    ai_department=entry.ai_department,
                    final_department=entry.final_department,
                    ai_urgency=entry.ai_urgency,
                    final_urgency=entry.final_urgency,
                    reason=entry.reason,
                    timestamp=entry.timestamp,
                ))
                if rec:
                    db.query(ComplaintRow).filter(
                        ComplaintRow.complaint_id == entry.complaint_id
                    ).update({
                        "status": rec["status"],
                        "category": rec["category"],
                        "department": rec["department"],
                        "urgency": rec["urgency"],
                    })

    # -- reads -------------------------------------------------------------
    def queue(self, limit: int = 100) -> list[dict]:
        rows = sorted(self.records.values(), key=lambda r: r.get("created_at", ""), reverse=True)
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
        return similarity.cluster(list(self.records.values()), self.index)

    # -- Natural-language query (supervisory) ------------------------------
    def nlq(self, question: str) -> dict:
        """Transparent NLQ. Gemini parses the question into STRUCTURED filters
        (robust to phrasing/language); the filters are then applied
        deterministically over the store and returned to the supervisor — so
        the query is powered by Gemini but stays fully auditable (no black box).
        Falls back to keyword parsing if Gemini is unavailable.
        """
        if gemini.is_available():
            try:
                recs, filters = self._gemini_filters(question)
                return self._format_nlq(question, recs, filters)
            except Exception:
                pass
        return self._keyword_nlq(question)

    def _gemini_filters(self, question: str) -> tuple[list[dict], list[str]]:
        schema = {
            "type": "OBJECT",
            "properties": {
                "district": {"type": "STRING"},
                "topic": {"type": "STRING"},
                "urgency": {"type": "STRING", "enum": ["Critical", "High", "Medium", "Low", ""]},
                "status": {"type": "STRING", "enum": ["Open", "Resolved", ""]},
                "safety_only": {"type": "BOOLEAN"},
                "min_age_days": {"type": "INTEGER"},
            },
            "required": ["district", "topic", "urgency", "status", "safety_only", "min_age_days"],
        }
        system = (
            "You extract structured query filters from a Haryana grievance "
            "supervisor's natural-language question. `district` must be a Haryana "
            "district name or empty. `topic` is a single department keyword "
            "(e.g. Water, Power, Roads, Revenue, Police, Health, Education, "
            "Municipal, Food, Pension) or empty. Use empty string / 0 / false when "
            "a field is not mentioned. `min_age_days` for 'long pending'/'delayed' "
            "questions (e.g. 7)."
        )
        f = gemini.generate_json(system, question, schema)
        recs = list(self.records.values())
        filters: list[str] = []

        dist = (f.get("district") or "").strip()
        match_d = next((d for d in DISTRICTS if d.lower() == dist.lower()), None)
        if match_d:
            recs = [r for r in recs if r.get("district") == match_d]
            filters.append(f"district = {match_d}")

        topic = (f.get("topic") or "").strip().lower()
        if topic:
            recs = [r for r in recs if topic in r.get("department", "").lower()
                    or topic in r.get("category", "").lower()]
            filters.append(f"topic ~ {topic}")

        urg = (f.get("urgency") or "").strip()
        if urg:
            recs = [r for r in recs if r.get("urgency") == urg]
            filters.append(f"urgency = {urg}")

        if f.get("safety_only"):
            recs = [r for r in recs if r.get("urgency") == "Critical" or r.get("is_safety_critical")]
            filters.append("safety-critical only")

        status = (f.get("status") or "").strip()
        if status == "Open":
            recs = [r for r in recs if r.get("status") in ("Open", "In Progress")]
            filters.append("status = Open/In Progress")
        elif status == "Resolved":
            recs = [r for r in recs if r.get("status") in ("Resolved", "Routed")]
            filters.append("status = Resolved")

        min_age = int(f.get("min_age_days") or 0)
        if min_age > 0:
            recs = [r for r in recs if self._age_days(r) >= min_age and r.get("status") in ("Open", "In Progress")]
            filters.append(f"pending ≥ {min_age} days")

        return recs, filters

    @staticmethod
    def _age_days(r: dict) -> int:
        try:
            return (datetime.now(timezone.utc) - datetime.fromisoformat(r["created_at"])).days
        except Exception:
            return 0

    def _format_nlq(self, question: str, recs: list[dict], filters: list[str]) -> dict:
        rows = sorted(recs, key=lambda r: r.get("created_at", ""), reverse=True)[:25]
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
                for r in rows
            ],
        }

    def _keyword_nlq(self, question: str) -> dict:
        """Offline keyword fallback when Gemini is unavailable."""
        q = question.lower()
        recs = list(self.records.values())
        filters: list[str] = []

        for d in DISTRICTS:
            if d.lower() in q:
                recs = [r for r in recs if r.get("district") == d]
                filters.append(f"district = {d}")
                break

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

        for u in ("critical", "high", "medium", "low"):
            if u in q:
                recs = [r for r in recs if r.get("urgency", "").lower() == u]
                filters.append(f"urgency = {u.title()}")
                break
        if "urgent" in q or "safety" in q:
            recs = [r for r in recs if r.get("urgency") == "Critical" or r.get("is_safety_critical")]
            filters.append("urgent / safety-critical")

        if "pending" in q or "open" in q or "unresolved" in q:
            recs = [r for r in recs if r.get("status") in ("Open", "In Progress")]
            filters.append("status = Open/In Progress")
        if "resolved" in q or "closed" in q:
            recs = [r for r in recs if r.get("status") in ("Resolved", "Routed")]
            filters.append("status = Resolved")

        if "delay" in q or "old" in q or "long pending" in q:
            recs = [r for r in recs if self._age_days(r) >= 7 and r.get("status") in ("Open", "In Progress")]
            filters.append("pending ≥ 7 days")

        return self._format_nlq(question, recs, filters)


store = Store()
