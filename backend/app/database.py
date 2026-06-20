"""SQLAlchemy engine and session factory.

DATABASE_URL defaults to SQLite (zero-config local dev). Set it to a
PostgreSQL connection string for AWS RDS staging / production.
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./complaints.db")

# AWS RDS / older Heroku-style URLs use postgres:// — SQLAlchemy needs postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

_is_sqlite = DATABASE_URL.startswith("sqlite")

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
    **({} if _is_sqlite else {"pool_size": 5, "max_overflow": 10}),
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
