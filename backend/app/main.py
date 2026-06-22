"""FastAPI app — Jansamvaad 2.0+ AI Grievance Intelligence & Decision Support.

Advisory-only. Every AI output is reviewable, overrideable and audit-logged.
Serves both the JSON API and the no-build React dashboard (static/).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# Load backend/.env regardless of the process working directory.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from .llm import get_provider  # noqa: E402
from .schemas import (  # noqa: E402
    AuditEntry,
    NLQRequest,
    OfficerDecision,
    TriageRequest,
    TriageResult,
)
from .store import store  # noqa: E402
from .taxonomy import ALL_CATEGORIES, ALL_DEPARTMENTS, DEPARTMENTS, DISTRICTS  # noqa: E402
from .triage import triage  # noqa: E402

app = FastAPI(
    title="Jansamvaad 2.0+ — AI Grievance Intelligence",
    description="Advisory AI decision-support layer for Haryana's Jansamvaad (CM Window).",
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def no_cache(request, call_next):
    """Prototype: never let the browser serve a stale dashboard from cache."""
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, must-revalidate"
    return response

_provider = get_provider()
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


# --------------------------------------------------------------------------
# Health / meta
# --------------------------------------------------------------------------
@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "provider": _provider.name,
        "sovereign_mode": _provider.name in ("ollama", "rules"),
        "time": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/taxonomy")
def taxonomy() -> dict:
    return {
        "departments": DEPARTMENTS,
        "categories": ALL_CATEGORIES,
        "department_names": ALL_DEPARTMENTS,
        "districts": DISTRICTS,
    }


# --------------------------------------------------------------------------
# Core: triage a complaint (advisory)
# --------------------------------------------------------------------------
@app.post("/api/triage", response_model=TriageResult)
def triage_endpoint(req: TriageRequest) -> TriageResult:
    if not req.text or not req.text.strip():
        raise HTTPException(status_code=400, detail="Complaint text is required.")
    cid = store.next_id()
    result = triage(_provider, store.index, store.records, req.text, req.district, cid)
    if req.persist:
        store.add_result(result)
    return result


# --------------------------------------------------------------------------
# Officer review queue + human-in-the-loop decision (audit)
# --------------------------------------------------------------------------
@app.get("/api/queue")
def queue() -> dict:
    return {"items": store.queue()}


@app.get("/api/complaint/{cid}")
def complaint(cid: str) -> dict:
    result = store.get_result(cid)
    rec = store.records.get(cid)
    if not rec:
        raise HTTPException(status_code=404, detail="Complaint not found.")
    return {"record": rec, "ai_result": result.model_dump() if result else None}


@app.post("/api/decision")
def decision(d: OfficerDecision) -> dict:
    rec = store.records.get(d.complaint_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Complaint not found.")
    result = store.get_result(d.complaint_id)
    ai_cat = result.analysis.category if result else rec.get("category", "")
    ai_dept = result.analysis.department if result else rec.get("department", "")
    ai_urg = result.analysis.urgency.value if result else rec.get("urgency", "")

    entry = AuditEntry(
        complaint_id=d.complaint_id,
        officer_id=d.officer_id,
        action=d.action,
        ai_category=ai_cat,
        final_category=d.final_category or ai_cat,
        ai_department=ai_dept,
        final_department=d.final_department or ai_dept,
        ai_urgency=ai_urg,
        final_urgency=(d.final_urgency.value if d.final_urgency else ai_urg),
        reason=d.reason,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    store.log_decision(entry)
    return {"ok": True, "audit": entry.model_dump()}


@app.get("/api/audit")
def audit() -> dict:
    return {"entries": [a.model_dump() for a in reversed(store.audit)]}


@app.delete("/api/admin/purge-live-records")
def purge_live_records() -> dict:
    from . import database
    from sqlalchemy import text
    if not database.is_available():
        return {"ok": False, "reason": "no database"}
    with database.session() as db:
        r = db.execute(text("DELETE FROM complaints WHERE source = 'live'"))
        deleted = r.rowcount
    live_ids = [cid for cid, rec in store.records.items() if rec.get("source") == "live"]
    for cid in live_ids:
        store.records.pop(cid, None)
        store.results.pop(cid, None)
    store.audit.clear()
    store._counter = 2000
    return {"ok": True, "deleted": deleted}


# --------------------------------------------------------------------------
# Supervisory intelligence: analytics, clusters, NLQ
# --------------------------------------------------------------------------
@app.get("/api/analytics")
def analytics() -> dict:
    return store.analytics()


@app.get("/api/clusters")
def clusters() -> dict:
    return {"clusters": store.clusters()}


@app.post("/api/nlq")
def nlq(req: NLQRequest) -> dict:
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question is required.")
    return store.nlq(req.question)


# --------------------------------------------------------------------------
# Static frontend (no-build React). Mounted last so /api/* wins.
# --------------------------------------------------------------------------
if STATIC_DIR.exists():
    @app.get("/")
    def root() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
