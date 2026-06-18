"""Noisy Indian-language text normalisation.

Directly answers the brief: "work with real-world complaint language,
including Hindi, English, mixed-language submissions, spelling variations,
abbreviations, and administrative terminology."

Deterministic and explainable: every expansion is recorded and surfaced to
the officer as a reason code, so nothing is silently rewritten.
"""

from __future__ import annotations

import re

from .taxonomy import ABBREVIATION_GAZETTEER, HINGLISH_GAZETTEER


def detect_script(text: str) -> str:
    """Cheap language hint from script — refined later by the LLM."""
    devanagari = len(re.findall(r"[ऀ-ॿ]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    if devanagari and latin:
        return "mixed"
    if devanagari:
        return "hi"
    if latin:
        return "en"
    return "other"


def normalize(text: str) -> tuple[str, list[str]]:
    """Return (normalized_text, list_of_applied_notes).

    Light, reversible-in-spirit normalisation: collapse whitespace, expand
    known administrative abbreviations, and annotate Hinglish domain terms so
    the model and the officer both see the canonical meaning.
    """
    notes: list[str] = []
    cleaned = re.sub(r"\s+", " ", text).strip()

    # Whole-word, case-insensitive abbreviation expansion.
    def expand_abbr(match: re.Match) -> str:
        token = match.group(0)
        key = token.lower().strip()
        expansion = ABBREVIATION_GAZETTEER.get(key) or ABBREVIATION_GAZETTEER.get(f" {key} ")
        if expansion:
            notes.append(f"Expanded abbreviation '{token}' → {expansion.strip()}")
            return f"{token} ({expansion.strip()})"
        return token

    abbr_pattern = re.compile(
        r"\b(" + "|".join(re.escape(k.strip()) for k in ABBREVIATION_GAZETTEER) + r")\b",
        re.IGNORECASE,
    )
    cleaned = abbr_pattern.sub(expand_abbr, cleaned)

    # Hinglish domain-term annotation (does not replace, only flags once).
    lowered = cleaned.lower()
    for term, canonical in HINGLISH_GAZETTEER.items():
        if re.search(r"\b" + re.escape(term) + r"\b", lowered):
            notes.append(f"Recognised term '{term}' → {canonical}")

    # De-dupe notes, keep order.
    seen: set[str] = set()
    deduped = [n for n in notes if not (n in seen or seen.add(n))]
    return cleaned, deduped
