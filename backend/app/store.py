"""PostgreSQL (or SQLite) backed data store.

API surface identical to the original in-memory store — no API routes change.

Startup sequence:
  1. CREATE TABLE IF NOT EXISTS for all three tables.
  2. Seed DB with historical records if the complaints table is empty.
  3. Rebuild the in-memory embedding index from all DB records.

The embedding index stays in-memory (rebuilt on each restart) because
storing float vectors in a plain SQL column is wasteful for a prototype;
production would use pgvector.
"""

from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone

from . import embeddings, gemini, similarity
from .database import SessionLocal, engine
from .models import AuditLog, Base, Complaint, TriageResultDB
from .schemas import AuditEntry, SimilarCase, TriageAnalysis, TriageResult
from .seed_data import seed_records
from .taxonomy import DISTRICTS


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

@contextmanager
def _db():
    """Write session: commits on clean exit, rolls back on exception."""
    sess = SessionLocal()
    try:
        yield sess
        sess.commit()
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()


def _read(query_fn):
    """One-shot read: opens a session, calls query_fn(db), closes cleanly."""
    sess = SessionLocal()
    try:
        return query_fn(sess)
    finally:
        sess.close()


# ---------------------------------------------------------------------------
# Row → dict / schema converters
# ---------------------------------------------------------------------------

def _comp_to_dict(row: Complaint) -> dict:
    return {
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
        "is_safety_critical": bool(row.is_safety_critical),
    }


def _row_to_triage_result(row: TriageResultDB) -> TriageResult:
    analysis = TriageAnalysis(**row.analysis_json)
    similar = [SimilarCase(**s) for s in (row.similar_cases_json or [])]
    return TriageResult(
        complaint_id=row.complaint_id,
        original_text=row.original_text or "",
        normalized_text=row.normalized_text or "",
        district=row.district or "",
        analysis=analysis,
        routing_office=row.routing_office or "",
        suggested_sla_days=row.suggested_sla_days or 7,
        sla_due=row.sla_due or "",
        similar_cases=similar,
        is_potential_duplicate=bool(row.is_potential_duplicate),
        provider=row.provider or "",
        created_at=row.created_at or "",
    )


def _row_to_audit_entry(row: AuditLog) -> AuditEntry:
    return AuditEntry(
        complaint_id=row.complaint_id,
        officer_id=row.officer_id,
        action=row.action,
        ai_category=row.ai_category,
        final_category=row.final_category,
        ai_department=row.ai_department,
        final_department=row.final_department,
        ai_urgency=row.ai_urgency,
        final_urgency=row.final_urgency,
        reason=row.reason or "",
        timestamp=row.timestamp,
    )


# ---------------------------------------------------------------------------
# Backward-compatible dict-like proxy
# Used by triage.py (RAG lookup) and main.py (complaint / decision endpoints).
# ---------------------------------------------------------------------------

class _RecordsProxy:
    def get(self, cid: str) -> dict | None:
        def _q(db):
            row = db.query(Complaint).filter(Complaint.complaint_id == cid).first()
            return _comp_to_dict(row) if row else None
        return _read(_q)


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class Store:
    def __init__(self) -> None:
        Base.metadata.create_all(bind=engine)
        self.index = embeddings.make_index()
        self._counter = 2000
        self._proxy = _RecordsProxy()
        self._load_seed()
        self._rebuild_index()

    # -- properties that match the old dict-based interface -----------------

    @property
    def records(self) -> _RecordsProxy:
        return self._proxy

    @property
    def audit(self) -> list[AuditEntry]:
        def _q(db):
            rows = db.query(AuditLog).order_by(AuditLog.id).all()
            return [_row_to_audit_entry(r) for r in rows]
        return _read(_q)

    # -- startup ------------------------------------------------------------

    def _load_seed(self) -> None:
        """Insert seed records on first run; update ID counter otherwise."""
        count = _read(lambda db: db.query(Complaint).count())
        if count > 0:
            self._sync_counter()
            return
        with _db() as db:
            for rec in seed_records():
                db.add(Complaint(**rec))

    def _sync_counter(self) -> None:
        ids = _read(lambda db: [r[0] for r in db.query(Complaint.complaint_id).all()])
        nums = [
            int(cid.split("-")[1])
            for cid in ids
            if cid.startswith("JS-") and cid.split("-")[1].isdigit()
        ]
        if nums:
            self._counter = max(nums)

    def _rebuild_index(self) -> None:
        pairs = _read(lambda db: [(r.complaint_id, r.text or "") for r in db.query(Complaint).all()])
        self.index.add_many(pairs)
        nums = [
            int(cid.split("-")[1])
            for cid, _ in pairs
            if cid.startswith("JS-") and cid.split("-")[1].isdigit()
        ]
        if nums:
            self._counter = max(self._counter, max(nums))

    # -- IDs ----------------------------------------------------------------

    def next_id(self) -> str:
        self._counter += 1
        return f"JS-{self._counter}"

    # -- writes -------------------------------------------------------------

    def add_result(self, result: TriageResult) -> None:
        comp = Complaint(
            complaint_id=result.complaint_id,
            text=result.original_text,
            district=result.district,
            category=result.analysis.category,
            department=result.analysis.department,
            urgency=result.analysis.urgency.value,
            status="Open",
            summary=result.analysis.summary,
            created_at=result.created_at,
            source="live",
            is_safety_critical=result.analysis.is_safety_critical,
        )
        triage_db = TriageResultDB(
            complaint_id=result.complaint_id,
            original_text=result.original_text,
            normalized_text=result.normalized_text,
            district=result.district,
            analysis_json=result.analysis.model_dump(),
            routing_office=result.routing_office,
            suggested_sla_days=result.suggested_sla_days,
            sla_due=result.sla_due,
            similar_cases_json=[s.model_dump() for s in result.similar_cases],
            is_potential_duplicate=result.is_potential_duplicate,
            provider=result.provider,
            created_at=result.created_at,
        )
        with _db() as db:
            db.merge(comp)
            db.merge(triage_db)
        self.index.add(result.complaint_id, result.original_text)

    def log_decision(self, entry: AuditEntry) -> None:
        with _db() as db:
            db.add(AuditLog(
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
            comp = db.query(Complaint).filter(Complaint.complaint_id == entry.complaint_id).first()
            if comp:
                if entry.action in ("accept", "override"):
                    comp.status = "Routed"
                comp.category = entry.final_category
                comp.department = entry.final_department
                comp.urgency = entry.final_urgency

    # -- reads --------------------------------------------------------------

    def queue(self, limit: int = 100) -> list[dict]:
        def _q(db):
            rows = db.query(Complaint).order_by(Complaint.created_at.desc()).limit(limit * 2).all()
            return [_comp_to_dict(r) for r in rows]
        rows = _read(_q)
        urg_rank = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
        rows.sort(key=lambda r: urg_rank.get(r.get("urgency", "Medium"), 2))
        return rows[:limit]

    def get_result(self, cid: str) -> TriageResult | None:
        def _q(db):
            row = db.query(TriageResultDB).filter(TriageResultDB.complaint_id == cid).first()
            return _row_to_triage_result(row) if row else None
        return _read(_q)

    # -- analytics ----------------------------------------------------------

    def analytics(self) -> dict:
        def _q(db):
            recs = [_comp_to_dict(r) for r in db.query(Complaint).all()]
            overrides = db.query(AuditLog).filter(AuditLog.action == "override").count()
            decisions = db.query(AuditLog).count()
            return recs, overrides, decisions

        recs, overrides, decisions = _read(_q)
        total = len(recs)
        by_dept = Counter(r.get("department", "Unknown") for r in recs)
        by_district = Counter(r.get("district", "Unknown") for r in recs)
        by_urgency = Counter(r.get("urgency", "Medium") for r in recs)
        by_status = Counter(r.get("status", "Open") for r in recs)
        by_category = Counter(r.get("category", "Unknown") for r in recs)
        safety = sum(1 for r in recs if r.get("is_safety_critical"))
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
        recs = _read(lambda db: [_comp_to_dict(r) for r in db.query(Complaint).all()])
        return similarity.cluster(recs, self.index)

    # -- NLQ ----------------------------------------------------------------

    def nlq(self, question: str) -> dict:
        if gemini.is_available():
            try:
                recs, filters = self._gemini_filters(question)
                return self._format_nlq(question, recs, filters)
            except Exception:
                pass
        return self._keyword_nlq(question)

    def _all_records(self) -> list[dict]:
        return _read(lambda db: [_comp_to_dict(r) for r in db.query(Complaint).all()])

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
        recs = self._all_records()
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
        q = question.lower()
        recs = self._all_records()
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
