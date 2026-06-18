# Jansamvaad 2.0+ — Solution Architecture

This document doubles as the source for the Sandbox application's **D1 (Solution
Architecture)**, **D2 (AI/ML Stack)**, **D3 (Integration)**, and **E1–E6
(Trustworthy AI)** answers.

---

## 1. System architecture

```
                              CITIZEN
                  (Hindi · English · Hinglish · noisy text)
                                  │
                                  ▼
                ┌─────────────────────────────────────┐
                │   Jansamvaad Portal (existing DPI)   │
                │   complaint text + metadata via API  │
                └───────────────────┬─────────────────┘
                                    ▼
        ┌──────────────────────────────────────────────────────┐
        │   1. PREPROCESSING  (preprocess.py, taxonomy.py)      │
        │   • script/language detection                         │
        │   • abbreviation gazetteer (UHBVN, PHED, BPL, FIR…)   │
        │   • Hinglish/transliteration normalisation            │
        │   • every expansion recorded → reason codes           │
        └──────────────────────────┬───────────────────────────┘
                                   ▼
        ┌──────────────────────────────────────────────────────┐
        │   2. AI GRIEVANCE INTELLIGENCE  (llm.py — pluggable)  │
        │   structured output, constrained to controlled        │
        │   department→category vocabulary                      │
        │                                                       │
        │     ┌── ClaudeProvider   (demo quality)               │
        │     ├── OllamaProvider   (PRODUCTION — self-hosted     │
        │     │                     open-weight, sovereign)      │
        │     └── RuleProvider     (offline fallback)            │
        │                                                       │
        │   → summary · category · department · urgency ·       │
        │     sentiment · confidence{} · reason_codes[]         │
        └──────────────────────────┬───────────────────────────┘
                                   ▼
        ┌──────────────────────────────────────────────────────┐
        │   3. DETERMINISTIC SAFETY FLOOR  (triage.py)          │
        │   department-validated rules can only RAISE urgency.  │
        │   sparking transformer / gas leak / contaminated      │
        │   water / assault → forced Critical (auditable).      │
        └──────────────────────────┬───────────────────────────┘
                                   ▼
        ┌──────────────────────────────────────────────────────┐
        │   4. ROUTING · SLA · RAG  (triage.py, similarity.py)  │
        │   • Citizen-Charter SLA + routing office              │
        │   • retrieve similar past complaints (TF-IDF→IndicBERT)│
        │   • duplicate detection                               │
        └──────────────────────────┬───────────────────────────┘
                                   ▼
        ┌──────────────────────────────────────────────────────┐
        │   5. HUMAN-IN-THE-LOOP  (officer dashboard)           │
        │   accept / override-with-reason / escalate            │
        │   → IMMUTABLE AUDIT LOG  (accountability + feedback)  │
        └───────────────┬───────────────────────┬──────────────┘
                        ▼                       ▼
        ┌──────────────────────┐   ┌──────────────────────────┐
        │  CASE ROUTED to       │   │  6. GOVERNANCE INTEL     │
        │  responsible officer  │   │  • analytics scorecards  │
        └──────────────────────┘   │  • systemic clustering   │
                                    │  • natural-language query│
                                    │  → Dept / CS / CM views  │
                                    └──────────────────────────┘
```

**Legend — open-source vs proprietary**

- **Open-source / standard:** FastAPI, Uvicorn, Pydantic, React, the TF-IDF
  engine; in production IndicBERT/MuRIL, sentence-transformers, Llama 3.1 / Gemma
  (open weights), PostgreSQL, ElasticSearch.
- **Proprietary (this solution's IP):** the controlled-vocabulary grievance
  taxonomy + SLA map, the deterministic safety-floor rule engine, the
  confidence + reason-code orchestration, the governance-intelligence clustering,
  and the transparent NLQ layer.

---

## 2. AI/ML stack (D2)

| Layer | Prototype (demo) | Production (sovereign) | Why |
|---|---|---|---|
| Complaint understanding / summarisation / classification | Claude `claude-opus-4-8` via structured outputs | **Llama 3.1 8B / Gemma**, self-hosted (Ollama / vLLM) | Open weights → runs on State Data Centre, no data egress, no per-call cost |
| Indian-language NLP | Claude (handles Hindi/Hinglish natively) | **IndicBERT / MuRIL** fine-tuned classifier | Purpose-built for Indian languages + code-mixing |
| Similarity / clustering / duplicates | pure-Python TF-IDF + cosine (zero downloads) | **sentence-transformers** (multilingual) | Prototype runs offline on a laptop; production gets semantic quality |
| Orchestration | FastAPI + a pluggable `LLMProvider` | same + LangChain (optional) | Single seam to swap engines |
| Storage / search | in-memory + TF-IDF index | **PostgreSQL + ElasticSearch** | Structured records + semantic retrieval |
| Frontend | React (no-build, vendored) | React (Vite build) | Lightweight, low-resource friendly |

**Why AI/ML and not just rules or a dashboard (C6):** complaint text is noisy,
multilingual, code-mixed and unstructured. Deterministic rules alone cannot read
intent, summarise, or cluster semantically-similar-but-differently-worded
complaints. AI does the *understanding*; rules enforce the *safety guarantees*;
humans make the *decisions*. The combination is the point.

---

## 3. Integration with existing DPI (D3)

- **Inbound:** a thin adapter consumes complaint text + metadata from the
  Jansamvaad backend (REST/DB view). No change to the citizen-facing portal.
- **Outbound:** triage results returned as structured suggestions to the officer
  workflow; routing/SLA written back through existing Jansamvaad APIs.
- **Stateless core + pluggable provider:** deploys on the Haryana State Data
  Centre (Meity-empanelled), on-prem GPU, or hybrid cloud-burst.
- **Standards-based:** REST/JSON, OpenAPI; aligns with India DPI patterns.

---

## 4. Trustworthy AI (E1–E6)

| Brief question | How this solution answers it |
|---|---|
| **E1 Data privacy / DPDPA-2023** | Sovereign provider keeps all citizen data on government infrastructure (no external API). PII-minimising preprocessing; deidentified data for training/eval; privacy-by-design (data used only for triage, access-controlled, audit-logged). |
| **E2 Explainability / bias** | Confidence scores + reason codes on every output; controlled vocabulary prevents arbitrary routing; override logging surfaces drift; bias testing across districts/languages via the override-rate metric. Contestability: officers can override and the citizen's complaint is never auto-rejected. |
| **E3 Accountability** | Advisory only; mandatory human review; immutable audit trail of AI suggestion → officer decision. The system augments dignity (faster redressal), never replaces judgement. |
| **E4 Protection from harm** | Deterministic safety floor guarantees life-safety complaints can't be down-prioritised. Proportionality: AI does decision-*support*, not enforcement. |
| **E5 Low-resource readiness** | Runs offline on a laptop with zero model downloads; degrades gracefully without connectivity or API access; small open models for constrained compute. |
| **E6 Excluded activities** | No weapons, no facial recognition / mass surveillance, no social scoring, no deceptive/deepfake tech. Confirmed compliant. |

---

## 5. Scalability & sustainability (F1–F2)

- **Replicability: High.** The taxonomy, gazetteer and SLA map are *data files*,
  not code — re-point them to another department, district, or state with no code
  change. The engine and dashboard are domain-agnostic.
- **Cost:** open self-hosted models remove per-call API cost; the same hardware
  serves all departments. Marginal cost of a new department ≈ a config file.
- **Operating model:** owned by the CM Grievance Cell / department IT, hosted on
  the State Data Centre; the human-in-the-loop override stream continuously
  improves the models (the audit flywheel) without external dependency.

---

## 6. MVP roadmap (F3)

| Milestone | Deliverable |
|---|---|
| **Month 1** | Ingest deidentified historical records; fine-tune IndicBERT classifier on validated routing history; baseline accuracy + override-rate metrics on a held-out set. |
| **Month 2** | Officer pilot in 1–2 departments; deterministic safety rules validated with department; explainability + audit in the loop; semantic clustering live. |
| **Month 3** | Sovereign self-hosted model on State Data Centre; supervisory NLQ + governance dashboards; KPI report (manual-effort reduction, consistency, SLA visibility). |
| **Demo Day** | End-to-end live demo on sandbox data; measured accuracy, override rate, and time-saved; deployment + scale-up plan. |
```
