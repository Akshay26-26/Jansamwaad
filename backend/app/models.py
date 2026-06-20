"""SQLAlchemy ORM models — three tables.

  complaints      — one row per complaint (the live system of record)
  triage_results  — full AI output for live-triaged complaints
  audit_log       — officer human-in-the-loop decisions
"""

from __future__ import annotations

from sqlalchemy import Boolean, Column, Integer, JSON, String, Text

from .database import Base


class Complaint(Base):
    __tablename__ = "complaints"

    complaint_id = Column(String(20), primary_key=True, index=True)
    text = Column(Text, nullable=False)
    district = Column(String(100), index=True)
    category = Column(String(200))
    department = Column(String(200), index=True)
    urgency = Column(String(20), index=True)
    status = Column(String(50), default="Open", index=True)
    summary = Column(Text)
    created_at = Column(String(50), index=True)
    source = Column(String(50))
    is_safety_critical = Column(Boolean, default=False)


class TriageResultDB(Base):
    """Full AI triage output — only exists for live-submitted complaints."""
    __tablename__ = "triage_results"

    complaint_id = Column(String(20), primary_key=True, index=True)
    original_text = Column(Text)
    normalized_text = Column(Text)
    district = Column(String(100))
    # TriageAnalysis stored as JSON — avoids a dozen narrow columns and lets the
    # schema evolve without a migration for every new analysis field.
    analysis_json = Column(JSON)
    routing_office = Column(String(200))
    suggested_sla_days = Column(Integer)
    sla_due = Column(String(50))
    similar_cases_json = Column(JSON)
    is_potential_duplicate = Column(Boolean, default=False)
    provider = Column(String(50))
    created_at = Column(String(50))


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    complaint_id = Column(String(20), index=True)
    officer_id = Column(String(100))
    action = Column(String(50))
    ai_category = Column(String(200))
    final_category = Column(String(200))
    ai_department = Column(String(200))
    final_department = Column(String(200))
    ai_urgency = Column(String(20))
    final_urgency = Column(String(20))
    reason = Column(Text)
    timestamp = Column(String(50))
