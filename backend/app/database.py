"""SQLAlchemy persistence layer.

Two tables: complaints (one row per grievance) and audit_entries (officer
decisions). Used by Store when DATABASE_URL env-var is set; otherwise the app
runs fully in-memory (offline / local-dev mode).
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import Boolean, Column, Integer, JSON, String, Text, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker


Base = declarative_base()


class ComplaintRow(Base):
    __tablename__ = "complaints"

    complaint_id = Column(String, primary_key=True)
    text = Column(Text, nullable=False, default="")
    district = Column(String, default="")
    category = Column(String, default="")
    department = Column(String, default="")
    urgency = Column(String, default="Medium")
    status = Column(String, default="Open")
    summary = Column(Text, default="")
    created_at = Column(String, default="")
    source = Column(String, default="live")
    is_safety_critical = Column(Boolean, default=False)
    triage_json = Column(JSON, nullable=True)


class AuditRow(Base):
    __tablename__ = "audit_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    complaint_id = Column(String, index=True)
    officer_id = Column(String, default="")
    action = Column(String, default="")
    ai_category = Column(String, default="")
    final_category = Column(String, default="")
    ai_department = Column(String, default="")
    final_department = Column(String, default="")
    ai_urgency = Column(String, default="")
    final_urgency = Column(String, default="")
    reason = Column(Text, default="")
    timestamp = Column(String, default="")


_engine = None
_SessionLocal = None


def init_db() -> bool:
    """Connect to DB, create tables if needed. Returns True if DB is available."""
    global _engine, _SessionLocal
    if _engine is not None:
        return True
    url = os.getenv("DATABASE_URL")
    if not url:
        return False
    try:
        _engine = create_engine(url, pool_pre_ping=True)
        _SessionLocal = sessionmaker(bind=_engine)
        Base.metadata.create_all(_engine)
        return True
    except Exception as exc:
        print(f"[db] Connection failed ({exc}). Running in-memory only.")
        _engine = None
        _SessionLocal = None
        return False


def is_available() -> bool:
    return _engine is not None


@contextmanager
def session() -> Generator[Session | None, None, None]:
    if _SessionLocal is None:
        yield None
        return
    db: Session = _SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
