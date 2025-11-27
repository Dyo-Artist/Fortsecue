# AGENTS

## Repository Purpose

This repository contains **LOGOS**, a local-first stakeholder intelligence tool.

LOGOS ingests documents, notes, and audio transcripts, extracts entities and commitments, and upserts them into a Neo4j graph. A small FastAPI + HTML UI allows basic ingest, search, graph views, and alerts.

High-level pipeline:

- ingest → transcribe (stub for now) → NLP extract → normalise → graph upsert → UI

## Tech Stack

- Python 3.11+
- FastAPI
- httpx
- Neo4j (via `logos/graphio/neo4j_client.py`)
- Optional local LLM via Ollama (`logos/interfaces/ollama_client.py`)
- Tests: `pytest`

## Agent Guidelines

1. **Safety and Scope**
   - Do NOT introduce any cloud dependencies or external SaaS services.
   - Keep LOGOS runnable locally with:
     - Python
     - Neo4j
     - (optionally) local Ollama

2. **Code Changes**
   - Prefer small, focused changes.
   - Keep public API endpoints and response shapes stable unless explicitly instructed.
   - All Cypher must use parameters; no string interpolation of values.
   - Respect the existing graph schema and upsert functions in `logos/graphio/upsert.py`.

3. **Testing**
   - Always keep `pytest -q` green.
   - Do NOT make tests depend on a running Neo4j or Ollama instance:
     - Use monkeypatching for drivers/clients.
   - If you change behaviour, add or update tests accordingly.

4. **Configuration**
   - Neo4j config must be env-driven:
     - `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `NEO4J_DATABASE`.
   - Ollama usage must be optional and gated by:
     - `LOGOS_USE_OLLAMA` (default: disabled).

5. **Files to Treat Carefully**
   - `logos/main.py`: only change endpoints or behaviour when explicitly requested.
   - `logos/graphio/neo4j_client.py`: keep `GraphUnavailable`, `ping`, and `run_query` semantics intact.
   - `logos/nlp/extract.py`: must continue to work in regex-only mode when Ollama is disabled.

6. **Documentation**
   - Keep `README.md` accurate for:
     - Installation
     - Configuration (Neo4j, optional Ollama)
     - Running the app
     - Basic usage from the UI and `/docs`.

## Current MVP Focus

- Make LOGOS easy to launch locally:
  - `uvicorn logos.main:app --reload`
  - Neo4j configured via env vars
  - Optional Ollama integration
- Ensure:
  - Ingest → preview → commit → search/graph/alerts works end-to-end.
