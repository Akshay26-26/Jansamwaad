"""Pydantic schemas — the structured contract for AI triage output.

Every field an officer needs to review, override, and audit a recommendation.
The LLM is constrained to return exactly this shape (structured outputs), which
is what makes the system *advisory and auditable* rather than a black box.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class UrgencyLevel(str, Enum):
    CRITICAL = "Critical"
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class Confidence(BaseModel):
    category: float = Field(ge=0, le=1)
    department: float = Field(ge=0, le=1)
    urgency: float = Field(ge=0, le=1)
    overall: float = Field(ge=0, le=1)


# ---- The model's structured analysis (what the LLM/provider returns) --------
class TriageAnalysis(BaseModel):
    """Pure analysis returned by the LLM provider, constrained to taxonomy."""
    detected_language: Literal["hi", "en", "mixed", "other"]
    summary: str = Field(description="One or two line neutral English summary")
    category: str = Field(description="MUST be one of the controlled categories")
    subcategory: str = ""
    department: str = Field(description="MUST be one of the controlled departments")
    urgency: UrgencyLevel
    is_safety_critical: bool = False
    sentiment: Literal["angry", "distressed", "neutral", "appreciative"] = "neutral"
    confidence: Confidence
    reason_codes: list[str] = Field(
        default_factory=list,
        description="Short phrases/signals that drove the classification — the explainability trail",
    )
    recommended_action: str = ""


class SimilarCase(BaseModel):
    complaint_id: str
    summary: str
    category: str
    district: str
    similarity: float
    status: str


# ---- The full enriched record served to the officer dashboard ---------------
class TriageResult(BaseModel):
    complaint_id: str
    original_text: str
    normalized_text: str
    district: str
    analysis: TriageAnalysis
    routing_office: str
    suggested_sla_days: int
    sla_due: str
    similar_cases: list[SimilarCase] = Field(default_factory=list)
    is_potential_duplicate: bool = False
    provider: str
    created_at: str


# ---- Officer human-in-the-loop decision (audit log) -------------------------
class OfficerDecision(BaseModel):
    complaint_id: str
    officer_id: str = "officer.demo"
    action: Literal["accept", "override", "escalate", "reject_ai"]
    final_category: Optional[str] = None
    final_department: Optional[str] = None
    final_urgency: Optional[UrgencyLevel] = None
    reason: str = ""


class AuditEntry(BaseModel):
    complaint_id: str
    officer_id: str
    action: str
    ai_category: str
    final_category: str
    ai_department: str
    final_department: str
    ai_urgency: str
    final_urgency: str
    reason: str
    timestamp: str


# ---- Request bodies ---------------------------------------------------------
class TriageRequest(BaseModel):
    text: str
    district: str = "Hisar"
    persist: bool = True


class NLQRequest(BaseModel):
    question: str
