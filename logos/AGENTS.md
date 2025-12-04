# AGENTS

## Repository Purpose

This repository contains **LOGOS**, a local-first stakeholder intelligence and governance engine.

LOGOS:

- Ingests documents, notes, and audio transcripts.
- Extracts stakeholders, interactions, commitments, issues, risks, topics, and outcomes.
- Normalises and upserts them into a Neo4j knowledge graph using a **Platonic/Socratic knowledge model** (Forms, Concepts, Particulars, Agents, Dialectical Lines).
- Exposes a FastAPI + HTML UI for ingest → preview → commit, search, stakeholder 360 views, project maps, and alerts.

High-level processing pipeline:

> ingest → parse/transcribe → NLP extract → normalise → graph upsert → reasoning/alerts → UI

LOGOS Core (the “brain”) is designed to be reusable across domains. The Stakeholder Engagement MVP is the first product built on top.

---

## Canonical Design Documents

**Before making non-trivial changes, agents MUST consult these docs. They are the source of truth.**

All are in the repo root:

- `System Architecture Document (SAD).md`  
  Overall architecture, components, and boundaries.

- `AI Model Design.md`  
  Model tiers (rule-only, local ML, local LLM), task routing, and evaluation assumptions.

- `Graph Schema & Knowledge Model Specification.md`  
  Neo4j labels, relationships, properties, and the Forms / Concepts / Particulars model.

- `Data Flow Diagram (DFD) and Entity-Relationship Diagram (ERD).md`  
  Logical data flows and the ERD backing the graph model.

- `Pipeline & Workflow Design.md`  
  Standard bundles (`RawInputBundle`, `ParsedContentBundle`, `ExtractionBundle`, `ResolvedBundle`, `UpsertBundle`, `ReasoningBundle`, `FeedbackBundle`) and pipelines (ingest, commit, reasoning/alerts, agents).

- `Knowledgebase & Prompt Design Guide.md`  
  Knowledgebase layout, domain profiles, Concepts, Topics, lexicons, prompts, rules, and how the system learns over time.

- `API & Integration Specification.md`  
  HTTP API contract (`/api/v1/...`), request/response shapes, and error model.

- `Use Case Document.md`  
  Actors and use cases (ingest, preview, commit, search, stakeholder 360, commitments, alerts, project maps, configuration).

### Mapping from Code to Docs

When changing:

- **Graph / Neo4j code** (`logos/graphio/**`):  
  Follow `Graph Schema & Knowledge Model Specification.md` and `Data Flow Diagram (DFD) and Entity-Relationship Diagram (ERD).md`.

- **Pipelines, bundles, or normalisation** (`logos/ingest/**`, `logos/normalise/**`, `logos/nlp/**`):  
  Follow `Pipeline & Workflow Design.md`, `AI Model Design.md`, and `Knowledgebase & Prompt Design Guide.md`.

- **HTTP API or FastAPI app** (`logos/main.py`, `logos/app.py`, `logos/services/**`):  
  Follow `API & Integration Specification.md`, `Use Case Document.md`, and `System Architecture Document (SAD).md`.

- **Knowledgebase, prompts, and configs** (`logos/knowledgebase/**`, prompt files when added):  
  Follow `Knowledgebase & Prompt Design Guide.md` and `AI Model Design.md`.

If code and docs disagree, prefer the docs and update them together with the code in the same PR.

---

## Agent Operating Rules

### 1. Safety and Scope

- Do **NOT** introduce any cloud dependencies or external SaaS services.  
- LOGOS must remain runnable **fully locally** with:
  - Python
  - Neo4j
  - Optional local LLM (e.g. Ollama) and optional local ASR/OCR
- No outgoing network calls other than:
  - Optional local LLM/ASR/OCR endpoints configured by env vars.
  - Neo4j.

### 2. Architecture and Boundaries

- Maintain the existing high-level architecture from the SAD:
  - `ingest/` → `nlp/` → `normalise/` → `graphio/` → `services/` → `templates/`.
- Do not collapse the system into a simple CRUD app. Preserve:
  - The **Forms / Concepts / Particulars / Agents** abstractions.
  - The **bundle-based pipelines** and learning loops.
- Any new feature must slot into the existing pipelines or be added as a new, clearly defined pipeline.

### 3. Pipelines and Bundles

- Do NOT change bundle shapes without updating `Pipeline & Workflow Design.md` and associated tests.
- The canonical bundle types are:
  - `RawInputBundle`
  - `ParsedContentBundle`
  - `ExtractionBundle`
  - `ResolvedBundle`
  - `UpsertBundle`
  - `ReasoningBundle`
  - `FeedbackBundle`
- Pipelines must be defined declaratively (via config / registry) and executed using the standard stage pattern.

### 4. Graph Schema

- All graph writes must respect `Graph Schema & Knowledge Model Specification.md`:
  - Node labels: `Person`, `Org`, `Project`, `ProjectComponent`, `Contract`, `Interaction`, `Commitment`, `Issue`, `Risk`, `Outcome`, `Topic`, `Document`, `Policy`, `Agent`, etc.
  - Relationship types: `WORKS_FOR`, `INVOLVED_IN`, `PARTY_TO`, `PARTICIPATED_IN`, `MENTIONS`, `MADE`, `RELATES_TO`, `RAISED_IN`, `IDENTIFIED_IN`, `INFLUENCES`, `ASSISTS`, `INSTANCE_OF`, etc.
- Use **stable `id` properties** and `MERGE` for idempotent upserts. Never rely on Neo4j internal IDs.
- All Cypher must use **parameters**; no string interpolation of values.

### 5. Knowledgebase, Concepts, and Prompts

- Follow `Knowledgebase & Prompt Design Guide.md` for:
  - Directory structure (`domain_profiles/`, `concepts/`, `topics/`, `lexicons/`, `prompts/`, `rules/`, `models/`, `workflows/`).
  - Representation of Forms, Concepts, Topics, lexicons, and rules.
  - Prompt templates and model tier routing.
- Do NOT hard-code domain-specific rules, thresholds, or wordlists in code if they belong in the knowledgebase.

### 6. API Surface

- Follow `API & Integration Specification.md` for:
  - Endpoint paths (`/api/v1/...`).
  - Request/response JSON shapes and error model.
- Do not change existing endpoint contracts unless the spec is updated and the change is clearly versioned.

---

## Code Change Guidelines

1. Prefer small, focused changes.
2. Keep public API endpoints, bundle types, and graph schema stable unless explicitly updating the relevant design docs.
3. When implementing a new feature:
   - Identify relevant docs and cite them in code comments where useful.
   - Reuse existing patterns (pipelines, bundles, services) before introducing new abstractions.

---

## Testing

- Always keep `pytest -q` green.
- Do **NOT** make tests depend on a running Neo4j, Ollama, or other external process:
  - Use monkeypatching or test doubles for drivers/clients.
- When changing behaviour (bundles, graph upserts, API responses, pipelines):
  - Add or update tests to lock in the new behaviour.
- Where practical, add tests that encode spec invariants from the design docs
  (e.g. graph labels/relationships, bundle fields).

---

## Configuration

- Neo4j config must be env-driven:
  - `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `NEO4J_DATABASE`.
- Optional local LLM usage must be gated by:
  - `LOGOS_USE_OLLAMA` (default: disabled).
- Any additional local AI services (ASR/OCR) must also be optional and configured by env vars. No hard-coded endpoints.

---

## Files to Treat Carefully

The following are high-impact and should not be changed without reading the associated design docs and understanding the impact:

- `logos/main.py`, `logos/app.py`  
  API surface and app wiring (`API & Integration Specification.md`, SAD).

- `logos/graphio/neo4j_client.py`, `logos/graphio/upsert.py`  
  Graph access and upsert semantics (`Graph Schema & Knowledge Model Specification.md`).

- `logos/ingest/**`, `logos/nlp/**`, `logos/normalise/**`  
  Pipelines, extraction, and normalisation (`Pipeline & Workflow Design.md`, `AI Model Design.md`).

- `logos/knowledgebase/**` (when added)  
  Domain profiles, Concepts, Topics, prompts, rules (`Knowledgebase & Prompt Design Guide.md`).

---

## Current MVP Focus

- Make LOGOS easy to launch locally:
  - `uvicorn logos.main:app --reload`
  - Neo4j configured via env vars
  - Optional Ollama integration for extraction/summaries
- Ensure the following works end-to-end and matches the design docs:
  - Ingest → preview → commit
  - Search and stakeholder/project views
  - Commitments management
  - Alerts and basic reasoning
- Keep LOGOS Core (the cognitive engine, pipelines, schema, knowledgebase) **modular and reusable** so it can power future modules beyond stakeholder engagement.
