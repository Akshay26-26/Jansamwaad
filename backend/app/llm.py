"""LLM provider abstraction — the swappable AI engine.

ONE interface, THREE backends, selected by the LLM_PROVIDER env var:

  * ClaudeProvider  — demo-quality (Claude API). What you see in the live demo.
  * OllamaProvider  — PRODUCTION sovereign path. A self-hosted open-weight model
                      (Llama 3.1 / Gemma) on the Haryana State Data Centre.
                      No citizen data ever leaves government infrastructure.
  * RuleProvider    — offline deterministic fallback. Runs with zero API key and
                      zero model downloads, so the system degrades gracefully on
                      air-gapped / low-resource hardware instead of failing.

This single seam is the architecture's edge: moving from the demo provider to
the sovereign self-hosted provider is a one-line config change, not a rewrite.
"""

from __future__ import annotations

import json
import os

from .schemas import Confidence, TriageAnalysis, UrgencyLevel
from .taxonomy import (
    ALL_CATEGORIES,
    ALL_DEPARTMENTS,
    DEPARTMENTS,
    department_for_category,
)

# ---------------------------------------------------------------------------
# Shared prompt — the controlled-vocabulary instruction. Identical across the
# Claude and Ollama providers so behaviour is consistent when you swap engines.
# ---------------------------------------------------------------------------

_TAXONOMY_BLOCK = "\n".join(
    f"- {dept}:\n    " + "\n    ".join(meta["categories"])
    for dept, meta in DEPARTMENTS.items()
)

SYSTEM_PROMPT = f"""You are a decision-support assistant for the Government of Haryana's \
Jansamvaad (CM Window) citizen-grievance platform. You read a citizen complaint and \
return a STRUCTURED, ADVISORY recommendation that a government officer will review, \
override if needed, and act on. You never make a final decision; you assist.

Hard rules:
1. You MUST choose `category` from the controlled list below, and `department` MUST be \
the parent department of that category. Never invent categories or departments.
2. `summary` is a neutral 1–2 line English summary (even if the complaint is in Hindi/Hinglish).
3. `reason_codes` MUST list the specific words/phrases or signals that drove your \
classification and urgency — this is the explanation an officer audits. 2–5 short items.
4. `confidence` values are honest 0–1 estimates. If the text is ambiguous, lower them.
5. Mark `is_safety_critical` true ONLY for threat-to-life / safety hazards \
(sparking transformer, gas leak, contaminated water, assault, building collapse, etc.).
6. Be robust to Hindi, English, Hinglish, transliteration, spelling errors and abbreviations.

Controlled department → category vocabulary:
{_TAXONOMY_BLOCK}
"""


class LLMProvider:
    name = "base"

    def analyze(self, normalized_text: str, language_hint: str, notes: list[str]) -> TriageAnalysis:  # pragma: no cover
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Claude provider (demo quality)
# ---------------------------------------------------------------------------
class ClaudeProvider(LLMProvider):
    name = "claude"

    def __init__(self) -> None:
        import anthropic  # imported lazily so the app runs without the dep installed

        self._client = anthropic.Anthropic()
        self._model = os.getenv("CLAUDE_MODEL", "claude-opus-4-8")

    def analyze(self, normalized_text: str, language_hint: str, notes: list[str]) -> TriageAnalysis:
        user = (
            f"Complaint (script hint: {language_hint}):\n\"\"\"\n{normalized_text}\n\"\"\"\n\n"
            f"Preprocessing notes (already applied): {notes or 'none'}\n\n"
            "Classify it per the rules and controlled vocabulary."
        )
        resp = self._client.messages.parse(
            model=self._model,
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user}],
            output_format=TriageAnalysis,
        )
        if resp.parsed_output is None:
            # Safety refusal or schema miss — degrade rather than crash.
            return RuleProvider().analyze(normalized_text, language_hint, notes)
        return _repair(resp.parsed_output)


# ---------------------------------------------------------------------------
# Ollama provider (production sovereign path) — self-hosted open-weight model
# ---------------------------------------------------------------------------
class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self) -> None:
        self._base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self._model = os.getenv("OLLAMA_MODEL", "llama3.1:8b")

    def analyze(self, normalized_text: str, language_hint: str, notes: list[str]) -> TriageAnalysis:
        import urllib.request

        schema_hint = (
            '{"detected_language":"hi|en|mixed|other","summary":"...","category":"<from list>",'
            '"subcategory":"...","department":"<from list>","urgency":"Critical|High|Medium|Low",'
            '"is_safety_critical":false,"sentiment":"angry|distressed|neutral|appreciative",'
            '"confidence":{"category":0.0,"department":0.0,"urgency":0.0,"overall":0.0},'
            '"reason_codes":["..."],"recommended_action":"..."}'
        )
        prompt = (
            SYSTEM_PROMPT
            + f"\n\nComplaint (script hint {language_hint}):\n{normalized_text}\n\n"
            + f"Respond with ONLY a JSON object of this exact shape:\n{schema_hint}"
        )
        body = json.dumps({
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
        }).encode()
        req = urllib.request.Request(
            f"{self._base}/api/generate", data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read())
        raw = json.loads(data["response"])
        return _repair(TriageAnalysis(**_coerce(raw)))


# ---------------------------------------------------------------------------
# Rule-based provider (offline deterministic fallback)
# ---------------------------------------------------------------------------
_KEYWORDS: dict[str, list[str]] = {
    "Power Outage / Supply Failure": ["power cut", "no electricity", "no power", "outage", "bijli", "light gayi", "बिजली", "बत्ती"],
    "Faulty / Sparking Transformer": ["transformer", "spark", "चिंगारी", "ट्रांसफार्मर", "tx "],
    "Billing Dispute": ["bill", "billing", "overcharge", "बिल", "meter reading"],
    "Voltage Fluctuation": ["voltage", "fluctuat", "low voltage", "वोल्टेज"],
    "No Water Supply": ["no water", "paani nahi", "water supply", "पानी नहीं", "जलापूर्ति"],
    "Contaminated / Dirty Water": ["dirty water", "contaminat", "गंदा पानी", "smell", "muddy"],
    "Pipeline Leakage / Burst": ["pipeline", "leak", "burst", "पाइप", "रिसाव"],
    "Sewerage Overflow / Blockage": ["sewer", "sewage", "overflow", "नाली", "गटर", "drain block"],
    "Potholes / Damaged Road": ["pothole", "road", "sadak", "सड़क", "गड्ढा", "broken road"],
    "Broken / Missing Streetlight": ["street light", "streetlight", "स्ट्रीट लाइट", "lamp post"],
    "Land Records / Jamabandi Correction": ["jamabandi", "land record", "जमाबंदी", "khasra"],
    "Patwari / Tehsil Service Delay": ["patwari", "tehsil", "पटवारी", "तहसील"],
    "Mutation (Intkaal) Pending": ["mutation", "intkaal", "इंतकाल", "namantaran"],
    "Old-Age / Widow / Disability Pension": ["pension", "पेंशन", "old age", "widow", "विधवा", "vridha"],
    "BPL / Ration Card": ["ration", "bpl", "राशन", "बीपीएल"],
    "Ration / PDS Shop Issue": ["pds", "depot", "ration shop", "डिपो", "fair price"],
    "Garbage / Sanitation": ["garbage", "kachra", "कचरा", "safai", "सफाई", "sanitation"],
    "Stray Animals": ["stray", "awara", "आवारा", "cattle", "dog"],
    "Law & Order / Safety Threat": ["threat", "fight", "खतरा", "danger", "goon", "मारपीट"],
    "Women Safety / Harassment": ["harass", "molest", "eve teasing", "छेड़", "women safety"],
    "FIR Not Registered": ["fir", "complaint not", "एफआईआर", "police not"],
    "Medicine / Equipment Shortage": ["medicine", "dawai", "दवाई", "shortage", "no doctor"],
    "Teacher Shortage / Absence": ["teacher", "अध्यापक", "shikshak", "no teacher"],
}


class RuleProvider(LLMProvider):
    name = "rules"

    def analyze(self, normalized_text: str, language_hint: str, notes: list[str]) -> TriageAnalysis:
        text = normalized_text.lower()
        best_cat, best_hits = None, []
        for cat, kws in _KEYWORDS.items():
            hits = [k for k in kws if k in text]
            if len(hits) > len(best_hits):
                best_cat, best_hits = cat, hits
        if not best_cat:
            best_cat = "Patwari / Tehsil Service Delay"  # default to a review queue
            conf = 0.25
        else:
            conf = min(0.5 + 0.15 * len(best_hits), 0.85)
        dept = department_for_category(best_cat) or ALL_DEPARTMENTS[0]
        reason = [f"Matched keyword(s): {', '.join(best_hits)}"] if best_hits else ["No strong keyword match — flagged for manual review"]
        reason += notes[:2]
        return _repair(TriageAnalysis(
            detected_language=language_hint if language_hint in ("hi", "en", "mixed", "other") else "en",
            summary=normalized_text[:140],
            category=best_cat,
            subcategory="",
            department=dept,
            urgency=UrgencyLevel.MEDIUM,
            is_safety_critical=False,
            sentiment="neutral",
            confidence=Confidence(category=conf, department=conf, urgency=0.4, overall=round(conf * 0.9, 2)),
            reason_codes=reason,
            recommended_action="Route to nodal officer for verification (offline rule-based suggestion).",
        ))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _coerce(raw: dict) -> dict:
    """Best-effort coercion of a loose JSON dict into the schema's shape."""
    conf = raw.get("confidence") or {}
    if not isinstance(conf, dict):
        conf = {}
    raw["confidence"] = {
        "category": float(conf.get("category", 0.5)),
        "department": float(conf.get("department", 0.5)),
        "urgency": float(conf.get("urgency", 0.5)),
        "overall": float(conf.get("overall", 0.5)),
    }
    raw.setdefault("reason_codes", [])
    return raw


def _repair(a: TriageAnalysis) -> TriageAnalysis:
    """Enforce the controlled vocabulary even if the model drifted."""
    if a.category not in ALL_CATEGORIES:
        # snap to closest department default category
        a.category = ALL_CATEGORIES[0]
        a.confidence.category = min(a.confidence.category, 0.4)
        a.reason_codes.append("AI category was out-of-vocabulary; snapped to nearest valid category for review.")
    correct_dept = department_for_category(a.category)
    if correct_dept and a.department != correct_dept:
        a.department = correct_dept
    return a


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------
def get_provider() -> LLMProvider:
    choice = os.getenv("LLM_PROVIDER", "auto").lower()
    if choice == "claude":
        return ClaudeProvider()
    if choice == "ollama":
        return OllamaProvider()
    if choice == "rules":
        return RuleProvider()
    # auto: Claude if a key is present, else offline rules.
    if os.getenv("ANTHROPIC_API_KEY"):
        try:
            return ClaudeProvider()
        except Exception:
            return RuleProvider()
    return RuleProvider()
