"""Thin Gemini REST client (no SDK dependency — keeps the stack light and the
calls transparent/auditable).

Used for ALL NLP tasks in the system:
  * generate_json() — complaint understanding / classification / summarisation /
    reason codes, and natural-language-query parsing, on Gemini 2.5 Flash Lite.
  * embed() / embed_batch() — semantic embeddings for similarity, clustering,
    duplicate detection and RAG retrieval (Gemini embedding model).

Network calls go through urllib with a short retry so the app degrades to the
offline engines if Gemini is unreachable rather than failing.
"""

from __future__ import annotations

import json
import os
import time

import httpx

_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# Shared keep-alive client — reuses TCP/TLS connections across calls (the
# generate + embed of a single triage, and across requests), removing a fresh
# handshake (2 extra round-trips) from every Gemini call. Big win on a
# high-latency link.
_client = httpx.Client(
    timeout=httpx.Timeout(60.0, connect=10.0),
    limits=httpx.Limits(max_keepalive_connections=8, max_connections=16, keepalive_expiry=120.0),
)


def api_key() -> str | None:
    return os.getenv("GEMINI_API_KEY") or None


def is_available() -> bool:
    return bool(api_key())


def gen_model() -> str:
    return os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")


def embed_model() -> str:
    return os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001")


class GeminiError(RuntimeError):
    pass


def _post(url: str, payload: dict, timeout: int = 60) -> dict:
    last_err: Exception | None = None
    for attempt in range(2):
        try:
            resp = _client.post(url, json=payload, timeout=timeout)
            # 429 = free-tier quota throttle: retry once briefly, then give up
            # fast so the caller fails over to the offline engine (no hang).
            if resp.status_code in (429, 500, 503) and attempt < 1:
                time.sleep(0.6)
                last_err = GeminiError(f"{resp.status_code}: {resp.text[:200]}")
                continue
            if resp.status_code >= 400:
                raise GeminiError(f"Gemini HTTP {resp.status_code}: {resp.text[:200]}")
            return resp.json()
        except httpx.RequestError as e:
            last_err = e
            time.sleep(0.5)
    raise GeminiError(f"Gemini request failed: {last_err}")


# ---------------------------------------------------------------------------
# Generative NLU — structured JSON output (Gemini 2.5 Flash Lite)
# ---------------------------------------------------------------------------
def generate_json(system: str, user: str, schema: dict, *, temperature: float = 0.0) -> dict:
    key = api_key()
    if not key:
        raise GeminiError("GEMINI_API_KEY not set")
    url = f"{_BASE}/{gen_model()}:generateContent?key={key}"
    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": schema,
            "temperature": temperature,
            # Disable Flash Lite's "thinking" step — this is a classification
            # task, so thinking only adds latency with no quality gain.
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    data = _post(url, payload)
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as e:
        raise GeminiError(f"Unexpected Gemini response: {json.dumps(data)[:400]}") from e
    return json.loads(text)


# ---------------------------------------------------------------------------
# Embeddings — for similarity / clustering / duplicate detection / RAG
# ---------------------------------------------------------------------------
def embed(text: str) -> list[float]:
    return embed_batch([text])[0]


def embed_batch(texts: list[str]) -> list[list[float]]:
    key = api_key()
    if not key:
        raise GeminiError("GEMINI_API_KEY not set")
    if not texts:
        return []
    model = embed_model()
    url = f"{_BASE}/{model}:batchEmbedContents?key={key}"
    payload = {
        "requests": [
            {
                "model": f"models/{model}",
                "content": {"parts": [{"text": t[:8000] or " "}]},
                # 768 dims keeps vectors compact and is plenty for short complaints
                "outputDimensionality": 768,
            }
            for t in texts
        ]
    }
    data = _post(url, payload)
    embs = data.get("embeddings", [])
    if len(embs) != len(texts):
        raise GeminiError(f"Embedding count mismatch: got {len(embs)} for {len(texts)} inputs")
    return [e["values"] for e in embs]
