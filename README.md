# Jansamvaad 2.0+ — AI Grievance Intelligence & Decision-Support Layer

> Advisory AI decision-support for the Government of Haryana's **Jansamvaad (CM Window)** citizen-grievance platform.
> Built for the **Haryana AI Sandbox** challenge: *"AI-supported complaint triaging and routing for Jansamvaad."*

It reads a citizen complaint (Hindi / English / Hinglish, noisy and abbreviated),
and returns an **advisory** recommendation that a government officer reviews,
overrides if needed, and acts on — with confidence scores, reason codes,
similar past cases, a deterministic safety floor, and a full audit trail.

**It never closes, rejects, or finally routes a complaint on its own.** Human-in-the-loop, by design.

---

## The edge (why this is not "a chatbot + a dashboard")

The challenge brief explicitly rejects generic chatbots, dashboard-only proposals,
full-automation claims, and opaque models. This solution is built around the opposite:

| Differentiator | Where it lives |
|---|---|
| **Sovereign / on-prem by design** — one config line swaps the demo's Claude engine for a self-hosted open-weight model (Llama 3.1 / IndicBERT). No citizen data need leave government infrastructure. | [`app/llm.py`](backend/app/llm.py) |
| **Explainability first** — every recommendation ships confidence scores + reason codes + retrieved similar cases (RAG). | [`app/triage.py`](backend/app/triage.py), [`app/schemas.py`](backend/app/schemas.py) |
| **Deterministic safety floor** — department-validated rules can only *raise* urgency, never lower it (a sparking transformer is always Critical). | [`app/triage.py`](backend/app/triage.py) |
| **Human-in-the-loop + audit flywheel** — every accept/override is logged; overrides become training feedback. | [`app/main.py`](backend/app/main.py) |
| **Governance intelligence** — systemic-issue clustering + natural-language query for supervisors. | [`app/similarity.py`](backend/app/similarity.py), [`app/store.py`](backend/app/store.py) |
| **Noisy Indian-language handling** — transliteration + Haryana abbreviation gazetteer, every expansion surfaced to the officer. | [`app/preprocess.py`](backend/app/preprocess.py), [`app/taxonomy.py`](backend/app/taxonomy.py) |
| **Low-resource ready** — runs fully offline on a laptop with **zero model downloads** (degrades to a deterministic engine with no API key). | whole stack |

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the full design.

---

## Quick start

```bash
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
# source .venv/bin/activate

pip install -r requirements.txt

# (optional) demo-quality engine — Claude. Without it, the app runs offline
# on the deterministic rule engine automatically.
cp .env.example .env          # then set ANTHROPIC_API_KEY

uvicorn app.main:app --port 8099
```

Open **http://127.0.0.1:8099**.

> No API key? It just works — the health badge shows **"On-prem (rules)"** and the
> system runs on the offline deterministic engine. Set `ANTHROPIC_API_KEY` in `.env`
> for the high-quality Claude engine, or `LLM_PROVIDER=ollama` for a self-hosted
> open-weight model.

### Three views

1. **Citizen Intake** — paste a complaint (try the Hindi/Hinglish samples) → AI triage with confidence, reason codes, similar cases, safety flag, SLA.
2. **Officer Review** — queue sorted by urgency → accept / override-with-reason → immutable audit trail.
3. **Governance Dashboard** — department/priority/district analytics, systemic-issue clusters, and a natural-language query box.

---

## Engine selection (`LLM_PROVIDER`)

| Value | Engine | Use |
|---|---|---|
| `auto` (default) | Claude if `ANTHROPIC_API_KEY` is set, else `rules` | Zero-config |
| `claude` | Claude API (`claude-opus-4-8`) | Demo quality |
| `ollama` | Self-hosted open-weight model | **Production sovereign path** |
| `rules` | Offline deterministic | Air-gapped / low-resource |

All four implement the same interface — moving from demo to production is a config change, not a rewrite.

---

## API

| Endpoint | Purpose |
|---|---|
| `POST /api/triage` | Advisory triage of a complaint |
| `GET /api/queue` | Officer review queue |
| `POST /api/decision` | Record accept/override (audit) |
| `GET /api/audit` | Audit trail |
| `GET /api/analytics` | Governance analytics |
| `GET /api/clusters` | Systemic-issue clusters |
| `POST /api/nlq` | Natural-language supervisory query |
| `GET /api/health` · `GET /api/taxonomy` | Meta |

---

## Safeguards & data

- **Advisory only.** No complaint is auto-closed, rejected, or finally routed.
- **Synthetic data only.** [`app/seed_data.py`](backend/app/seed_data.py) contains generated, deidentified records — no real citizen data.
- **DPDPA-2023 aligned.** PII-minimising by design; the sovereign provider keeps all data on government infrastructure. See [`ARCHITECTURE.md`](ARCHITECTURE.md) § Trustworthy AI.
