Pipeline & Workflow Design
Product: LOGOS – Cognitive Engine + Stakeholder Engagement MVP
________________________________________
1. Introduction
1.1 Purpose
This document defines how LOGOS orchestrates ingest, reasoning, commit, memory, and collaboration workflows. It explains the standard bundle types, declarative pipeline configuration, and how multi-user sync and multi-tier memory are woven through each stage.
1.2 Scope
•	Ingest, preview, commit, reasoning/alerts, and background consolidation pipelines.
•	Bundle lifecycle, including memory tier markers and dynamic schema awareness.
•	Real-time collaboration (pub/sub broadcast) that follows pipeline completion.
•	Knowledgebase update hooks that allow the schema and concepts to evolve at runtime.
Out of scope: low-level FastAPI route handlers (see API & Integration Specification) and Neo4j driver details (see Graph Schema & Knowledge Model Specification).
1.3 Design Principles
•	Declarative: pipelines are defined in logos/knowledgebase/workflows/pipelines.yml and can be changed without code edits.
•	Composable bundles: stages read and write bundle objects; bundle shapes are stable and shared across pipelines.
•	Dynamic schema and knowledgebase: stages must read type definitions from knowledgebase YAML and may write usage updates or new concepts back.
•	Memory-aware: every stage declares what belongs in short-term (ephemeral), mid-term (cached with decay), or long-term (Neo4j/knowledgebase) memory.
•	Collaborative: commit-like pipelines end with a sync broadcast so other users/agents receive updates in real time.
________________________________________
2. Bundles and Memory Tiers
Canonical bundle types (shared across pipelines):
•	RawInputBundle: raw file/audio/input metadata; short-term memory only.
•	ParsedContentBundle: structured text, attachments, and parsing diagnostics; short-term.
•	ExtractionBundle: entities, relationships, commitments, sentiment, topics; short-term with mid-term cache option for replays.
• ResolvedBundle: entity resolution decisions (candidate matches with confidence, chosen canonical ids) plus dialectical_lines for Socratic graph links; short-term with mid-term retention for traceability.
•	UpsertBundle: graph-ready nodes/relationships plus provenance, including dialectical_lines for dialectic edges; eligible for long-term persistence (Neo4j) but retains memory markers for what should also refresh mid-term caches.
•	ReasoningBundle: risk/influence scores, alerts, explanations; short-term results with explicit flags indicating what should be promoted to long-term (e.g., derived scores) or kept in mid-term (e.g., hypotheses).
•	FeedbackBundle: user or agent feedback on extractions/resolutions; mid-term by default and written to long-term if it changes the knowledgebase or graph.
•	ConsolidationBundle (new): produced by periodic consolidation pipeline to decide what short-term/mid-term artefacts get promoted to long-term or deprecated.
Memory semantics:
•	Short-term: transient, tied to a request/preview window. Do not persist unless flagged.
•	Mid-term: cached with decay (e.g., local store or in-process cache) for reprocessing or reconciliation; cleaned by consolidation tasks.
•	Long-term: durable stores (Neo4j, knowledgebase files). Only promoted when confidence and user/agent approval warrant it.
Bundle fields now allow memory markers, e.g., should_persist (bool), persist_to ("graph"|"knowledgebase"), ttl_hint, and usage_score deltas that feed schema scoring.
________________________________________
3. Pipeline Catalogue (declarative in workflows/pipelines.yml)
3.1 Ingest Pipeline (upload → preview)
Stages:
1) ReceiveInput: accept uploads or API payloads; emit RawInputBundle.
2) ParseOrTranscribe: convert files/audio to text; emit ParsedContentBundle.
3) NLPExtract: run NER/RE/commitment/topic extraction; emit ExtractionBundle with memory markers for potential long-term topics/concepts.
4) NormaliseAndResolve: contextual identity resolution with confidence scores and candidate sets; emit ResolvedBundle (short-term, with mid-term cache option).
5) DraftUpsertBuild: assemble graph-ready structures from schema YAML (no hard-coded labels); emit UpsertBundle marked as preview_only.
6) KnowledgebaseUpdateStage (new): compare extracted concepts/labels against knowledgebase; queue additions/usage increments in a ConsolidationBundle fragment.
7) PreviewAssemble: collate preview payload for UI; keep short-term only.
3.2 Commit Pipeline (preview → graph write → broadcast)
Stages:
1) LoadPreview: load stored UpsertBundle from preview cache.
2) ApplyEdits: overlay user edits/approvals.
3) SchemaValidate: ensure all node/relationship types exist in knowledgebase YAML; create provisional definitions if new types are approved, tagging metadata (introduction_version, added_by).
4) GraphUpsert: generic MERGE using schema definitions (see Graph Schema & Knowledge Model Specification).
5) KnowledgebasePersist: write back schema usage metrics and any newly approved types to logos/knowledgebase (with change log entries).
6) SyncBroadcastStage (new): publish commit results (affected ids, schema changes, memory markers) to real-time channels (WebSocket/pub/sub) so other users/agents update views.
3.3 Knowledgebase Update Pipeline (concept edits, rule changes)
•	Triggered by domain profile edits or auto-learning events.
•	Stages: LoadCurrentSchema → ApplyEdit → ValidateConsistency → PersistChangeLog → SyncBroadcastStage.
3.4 Reasoning & Alerts Pipeline
•	Consumes UpsertBundle or graph snapshots.
•	Stages: FetchContext → ComputeScores (risk/influence/path reasoning) → DecidePersistence (mark which scores enter long-term) → AlertEvaluation → FeedbackBundle emit → SyncBroadcastStage for alert changes.
3.5 Memory Consolidation Pipeline (periodic/background)
•	Stages: GatherCandidates (short/mid-term caches) → ScoreForPromotion (using usage_frequency, feedback signals) → PromoteOrDeprecate (write to Neo4j/knowledgebase or mark expired) → Emit ConsolidationBundle for audit.
3.6 Agent/Query Pipelines
•	Follow similar stage patterns but must respect memory markers and dynamic schema; when agents craft new concepts or prompts, they route through the Knowledgebase Update Pipeline and then broadcast.
________________________________________
4. Workflow Execution Model
•	Pipelines are referenced by id in logos/knowledgebase/workflows/pipelines.yml with stage order, required bundles, and feature flags (memory tiers, broadcast).
•	Stages are pure functions over bundles; they may add telemetry (usage_frequency, last_seen_at) that feeds schema scoring.
•	Pipelines may be chained: ingest → preview → commit automatically schedules Knowledgebase Persist + SyncBroadcast.
•	Failures are retried per-stage; bundle snapshots (short-term) can be replayed for auditing or recovery.
________________________________________
5. Multi-user Collaboration & Sync
•	Pub/Sub model: after commit, concept edits, or alert updates, SyncBroadcastStage emits events (affected node ids, relationships, schema changes, bundle metadata).
•	Transport: WebSocket channel exposed by the API layer plus an internal event bus; both reuse the same payload schema.
•	Clients: UI tabs, agents, and background services subscribe to keep views consistent (stakeholder pages, search caches, alert panels).
•	Conflict handling: edits include version stamps; conflicting commits trigger a CONFLICT response and can be reconciled by reloading the latest bundle and re-applying deltas.
________________________________________
6. Memory Management in Pipelines
•	ReasoningBundle chooses what is promoted to long-term (e.g., confirmed risk scores) vs. mid-term (hypotheses needing confirmation).
•	NormaliseAndResolve keeps multiple candidates with confidence scores; identity choices can be revised when new evidence arrives (feedback can demote/promote).
•	ConsolidationBundle aggregates what to persist or decay; KnowledgebasePersist and GraphUpsert read its markers to avoid globbing all data into Neo4j.
•	Short-term artefacts expire on schedule; mid-term caches have TTL/decay settings defined in knowledgebase/workflows/pipelines.yml.
________________________________________
7. Knowledgebase Read/Write Flow
•	Pipelines always read schema, concept, prompt, and rule definitions from logos/knowledgebase (no hard-coded enums).
•	Usage telemetry and learned additions are written back safely:
o	Schema usage counters and last_seen_at.
o	New Concepts/Topics/relationship templates with metadata (introduction_version, added_by).
o	Prompt/rule tweaks triggered by feedback (logged with change reason).
•	Writebacks preserve YAML formatting and append change-log entries so edits remain auditable.
________________________________________
8. Alignment with Dynamic Schema and Graph Writes
•	GraphUpsert stages never assume fixed labels; they fetch allowed labels/types from the active schema YAML and fall back to creating new definitions if permitted.
•	INSTANCE_OF links are created dynamically for newly introduced Particular labels so the Forms/Concepts/Particulars model stays intact.
•	Relationship creation supports any schema-defined type; if a new type appears in a bundle, the pipeline validates and registers it before merging.
________________________________________
9. Operational Considerations
•	Scheduling: ingest/commit run on-demand; consolidation and alert sweeps run on intervals configured in workflows/pipelines.yml.
•	Observability: each stage logs bundle ids, schema version, memory tier actions, and broadcast results for traceability.
•	Testing: bundle fixtures in tests/ should mirror the declarative schemas; adding or changing bundle fields requires updating this doc and corresponding tests.
