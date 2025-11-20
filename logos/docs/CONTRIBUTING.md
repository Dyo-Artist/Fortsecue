You are implementing the LOGOS system inside this repository.

High-level purpose:
LOGOS is a local-first, privacy-preserving stakeholder/relationship intelligence system. It ingests unstructured interactions (calls, documents, notes), extracts entities and relationships, and upserts them into a Neo4j knowledge graph for search, visualisation, and alerts.

Authoritative design:
All requirements and architecture are defined in the /docs folder of the LOGOS project (SRS, AI Model Design, Data Flow & ERD, System Architecture, Use Cases). When implementing or modifying code, you must:
- Follow those documents as the source of truth.
- Preserve the ingest → transcribe → nlp_extract → normalise → graphio → ui pipeline.
- Target Python 3.11+ and Neo4j 4.x/5.x.
- Minimise external services; prefer local, pluggable components.

Current repo structure:
- app.py           → FastAPI entrypoint and HTTP API.
- config.py        → Configuration and settings.
- ingest/          → Ingestion of audio/docs into internal Interaction payloads.
- interfaces/      → Stub or adapter interfaces (ASR, NER, sentiment, etc).
- nlp/             → Entity/relationship extraction and sentiment logic.
- tests/           → Pytest suite (graph client, search endpoint, upsert flow).

Core responsibilities:
1) Ingest
   - Provide functions to ingest audio and documents:
     - POST /ingest/audio
     - POST /ingest/doc
   - Return an internal interaction_id and a preview of extracted entities/relationships before commit.

2) NLP extraction
   - Implement modular NER, relation extraction, and sentiment in nlp/ using interfaces/ as pluggable backends.
   - Output a normalised internal structure with:
     - entities: Person, Org, Project, Contract, Topic, Commitment, Interaction
     - relationships: WORKS_FOR, INVOLVED_IN, PARTY_TO, MENTIONS, MADE, RELATES_TO, INFLUENCES
     - interaction metadata: timestamps, sentiment, summary, source_uri.

3) Normalisation
   - Deduplicate and resolve entities (e.g. same person name in same org).
   - Map extracted mentions to canonical IDs used in the graph layer.

4) Graph upsert (Neo4j)
   - Implement a dedicated graph client and upsert layer (graphio/ module, to be created if missing).
   - Use parameterised Cypher ONLY (no string concatenation).
   - Upsert nodes and relationships according to the LOGOS graph schema:
     - Person {id, name, title, email, org_id, influence_score}
     - Org {id, name, domain, sector}
     - Project {id, name, status}
     - Contract {id, sap_id, value, start_date, end_date}
     - Topic {id, name}
     - Commitment {id, text, due_date, status}
     - Interaction {id, type, at, source_uri, sentiment, summary}
   - Relationships:
     - (:Person)-[:WORKS_FOR]->(:Org)
     - (:Person)-[:INVOLVED_IN]->(:Project)
     - (:Org)-[:PARTY_TO]->(:Contract)
     - (:Interaction)-[:MENTIONS]->(:Topic|:Org|:Person|:Project|:Contract)
     - (:Person)-[:MADE]->(:Commitment)
     - (:Commitment)-[:RELATES_TO]->(:Project|:Contract)
     - (:Person)-[:INFLUENCES {weight}]->(:Person)

5) API & UI
   - app.py exposes at least:
     - POST /ingest/audio
     - POST /ingest/doc
     - POST /commit/{interaction_id}
     - GET  /search?q=...
     - GET  /graph/ego?person_id=...
     - GET  /alerts
   - Adhere to payload shapes defined in the LOGOS design docs.

Implementation rules:
- Keep modules small and focused. Do not mix HTTP, NLP, and DB logic in one file.
- All external integration points go via interfaces/ (ASR, transformers, etc) so they can be swapped.
- Prefer pure functions and explicit dependencies over global state.
- Every Interaction, node, and edge must carry provenance data (source_uri and last_seen where applicable).
- Maintain and extend the tests/ directory; new functionality must be covered by tests where practical.

When making changes:
- First, read existing files in this repo (app.py, config.py, ingest/, interfaces/, nlp/, tests/).
- Align new code to the existing style and the LOGOS design docs.
- Do not invent new concepts that conflict with the defined schema or pipeline.
- If behaviour is unclear, choose the option that best fits the LOGOS architecture and note assumptions in concise comments.
