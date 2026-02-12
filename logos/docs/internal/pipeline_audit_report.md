# LOGOS Pipeline Audit Report

## Scope
Repository: `Dyo-Artist/Fortsecue`  
Audit focus:
1. Pipeline YAML files and stage registries
2. Execution paths for `POST /ingest`, `POST /commit`, `GET /alerts`, and agent dialogue endpoint
3. Which stage functions are actually executed
4. Stubbed/duplicate/unused learning and stage wiring

---

## 1) Pipeline YAML files and stage registries

### Pipeline YAML inventory

| File | Registry style | Declared pipelines |
|---|---|---|
| `logos/knowledgebase/pipelines.yml` | Stage IDs resolved by `logos.core.pipeline_executor.STAGE_REGISTRY` | `pipeline.interaction_ingest`, `pipeline.interaction_commit`, `pipeline.reasoning_alerts`, `pipeline.concept_update`, `pipeline.agent_dialogue` |
| `logos/knowledgebase/workflows/pipelines.yml` | Fully-qualified callable paths resolved by `logos.workflows.registry._resolve_callable` | `ingest_preview`, `commit_interaction`, `memory_consolidation` |

### Stage registries inventory

#### Active registry path (used by API routes)
- `logos.core.pipeline_executor.STAGE_REGISTRY` is the active runtime registry behind `run_pipeline(...)` imported by routes in:
  - `logos/main.py`
  - `logos/api/routes/ingest.py`
  - `logos/api/routes/agents.py`

Registered stage IDs include:
- Core wrapper stages:
  - `ingest.validate_input`
  - `ingest.parse_or_transcribe`
  - `nlp.extract`
  - `normalise.resolve_entities`
  - `preview.assemble`
  - `commit.validate`
  - `graph.upsert`
  - `alerts.evaluate`
  - `learn.capture_feedback`
- Additional imported pipeline modules:
  - `concepts.update`
  - `S7_REFLECT_AND_LEARN`
  - `R1_COLLECT_TARGETS`, `R2_COMPUTE_SCORES`, `R3_APPLY_RULES_AND_MODELS`, `R4_MATERIALISE_ALERTS`
  - `A1_PARSE_QUERY`, `A2_PLAN_DIALECTIC`, `A3_QUERY_GRAPH`, `A4_COMPOSE_RESPONSE`, `A5_CAPTURE_FEEDBACK`

#### Legacy/alternate registry path (declared but currently unreferenced)
- `logos.workflows.registry.run_pipeline(...)` loads from `logos/knowledgebase/workflows/pipelines.yml` and resolves stage callables dynamically.
- No current route/module imports this `run_pipeline` function; it appears dormant in current app wiring.

---

## 2) Execution paths from required endpoints

## A) `POST /ingest` execution path

`/ingest` as a literal path is not defined. The implemented ingest entrypoints are:
- `POST /ingest/doc`
- `POST /ingest/note`
- `POST /ingest/audio`
- `POST /api/v1/ingest/text` (alias to note ingest)

### Runtime path (all ingest entrypoints converge)
1. Route handler creates `InteractionMeta`, stores raw text in staging, builds `RawInputBundle`.
2. Route calls `run_pipeline("pipeline.interaction_ingest", raw_bundle, context)`.
3. `pipeline.interaction_ingest` stages (from `logos/knowledgebase/pipelines.yml`):
   1. `ingest.validate_input` → `stage_validate_input` → `legacy_stages.require_raw_input`
   2. `ingest.parse_or_transcribe` → `stage_parse_or_transcribe` → `legacy_stages.tokenise_text`
   3. `nlp.extract` → `stage_nlp_extract` → `legacy_stages.apply_extraction` then `legacy_stages.sync_knowledgebase`
   4. `normalise.resolve_entities` → `stage_normalise` (**no-op passthrough**)
   5. `preview.assemble` → `stage_preview` → `legacy_stages.build_preview_payload` + staging persistence

## B) `POST /commit` execution path

`/commit` as a literal path is not defined. Commit entrypoints are:
- `POST /api/v1/interactions/{interaction_id}/commit`
- Legacy alias: `POST /commit/{interaction_id}`

### Runtime path (both commit entrypoints converge)
1. Route loads preview bundle (API route accepts edited `PreviewBundle`; legacy loads staged preview).
2. Route calls `run_pipeline("pipeline.interaction_commit", preview, context)`.
3. `pipeline.interaction_commit` stages:
   1. `commit.validate` → `stage_commit_validate` → `legacy_stages.require_preview_payload` + `legacy_stages.capture_preview_memory`
   2. `graph.upsert` → `stage_graph_upsert` → `legacy_stages.resolve_entities_from_graph` + `legacy_stages.build_interaction_bundle_stage` + `legacy_stages.upsert_interaction_bundle_stage`
   3. `alerts.evaluate` → `stage_alerts` (**placeholder passthrough**)
   4. `learn.capture_feedback` → `stage_feedback` → `legacy_stages.persist_session_memory`
   5. `S7_REFLECT_AND_LEARN` → `stage_reflect_and_learn`

## C) `GET /alerts` execution path

There are two alert endpoints with different behavior:

1. `GET /alerts` in `logos/main.py`:
   - Executes two direct Cypher queries through `run_query(...)`
   - Returns unresolved commitments and sentiment drop payload
   - **Does not call a pipeline**

2. `GET /api/v1/alerts` in `logos/api/routes/alerts.py`:
   - Calls `graph_queries.list_alerts(...)`
   - Returns paginated materialized alerts
   - **Does not call a pipeline**

## D) Agent dialogue endpoint execution path

Endpoint: `POST /api/v1/agent/query`

1. Route builds `input_bundle` with `query`, optional stakeholder/project context.
2. Route calls `run_pipeline("pipeline.agent_dialogue", input_bundle, ctx)`.
3. `pipeline.agent_dialogue` stages:
   1. `A1_PARSE_QUERY`
   2. `A2_PLAN_DIALECTIC`
   3. `A3_QUERY_GRAPH`
   4. `A4_COMPOSE_RESPONSE`
   5. `A5_CAPTURE_FEEDBACK`
4. Route persists feedback again via `append_feedback(...)` using returned `feedback_bundle` payload.

---

## 3) Which stage functions are actually executed

### Definitely executed in current endpoint wiring

| Pipeline | Stage ID | Stage function |
|---|---|---|
| `pipeline.interaction_ingest` | `ingest.validate_input` | `logos.core.pipeline_executor.stage_validate_input` |
|  | `ingest.parse_or_transcribe` | `logos.core.pipeline_executor.stage_parse_or_transcribe` |
|  | `nlp.extract` | `logos.core.pipeline_executor.stage_nlp_extract` |
|  | `normalise.resolve_entities` | `logos.core.pipeline_executor.stage_normalise` |
|  | `preview.assemble` | `logos.core.pipeline_executor.stage_preview` |
| `pipeline.interaction_commit` | `commit.validate` | `logos.core.pipeline_executor.stage_commit_validate` |
|  | `graph.upsert` | `logos.core.pipeline_executor.stage_graph_upsert` |
|  | `alerts.evaluate` | `logos.core.pipeline_executor.stage_alerts` |
|  | `learn.capture_feedback` | `logos.core.pipeline_executor.stage_feedback` |
|  | `S7_REFLECT_AND_LEARN` | `logos.pipelines.interaction_commit.stage_reflect_and_learn` |
| `pipeline.agent_dialogue` | `A1_PARSE_QUERY` | `logos.pipelines.agent_dialogue.stage_parse_query` |
|  | `A2_PLAN_DIALECTIC` | `logos.pipelines.agent_dialogue.stage_plan_dialectic` |
|  | `A3_QUERY_GRAPH` | `logos.pipelines.agent_dialogue.stage_query_graph` |
|  | `A4_COMPOSE_RESPONSE` | `logos.pipelines.agent_dialogue.stage_compose_response` |
|  | `A5_CAPTURE_FEEDBACK` | `logos.pipelines.agent_dialogue.stage_capture_feedback` |

### Declared and registered, but not executed by any current route-triggered path

| Pipeline | Status |
|---|---|
| `pipeline.reasoning_alerts` | Declared in YAML and stage IDs are registered, but no route/service invocation found (`run_pipeline("pipeline.reasoning_alerts", ...)` absent). |
| `pipeline.concept_update` | Declared in YAML and stage is registered, but no invocation found. |

### Legacy workflow registry status

- `logos/knowledgebase/workflows/pipelines.yml` pipelines (`ingest_preview`, `commit_interaction`, `memory_consolidation`) are not triggered by current app routes because `logos.workflows.registry.run_pipeline` is not imported/used by route handlers.

---

## 4) Findings: stubs, duplicates, unreferenced declarations, and learning hooks

## A) Stubbed/no-op stages

1. **`normalise.resolve_entities`**
   - Implemented as `stage_normalise(bundle, ctx) -> bundle` with a placeholder comment.
   - No resolution logic is executed at ingest stage despite declarative stage presence.

2. **`alerts.evaluate`**
   - Implemented as `stage_alerts(bundle, ctx) -> bundle` with placeholder pragma comment.
   - Commit pipeline includes an alert evaluation stage that currently does nothing.

## B) Duplicate/overlapping functionality

1. **Identity resolution overlap across ingest and commit pipeline design**
   - In ingest pipeline: stage `normalise.resolve_entities` is declared but currently no-op.
   - In commit pipeline: `graph.upsert` wrapper always performs `resolve_entities_from_graph(...)` before bundle upsert.
   - Net effect: entity resolution behavior effectively lives in commit flow, while ingest declaratively claims normalization stage.

2. **Feedback persistence overlap in agent dialogue**
   - Pipeline stage `A5_CAPTURE_FEEDBACK` constructs feedback payload (`feedback_bundle` in pipeline result).
   - Route handler then persists feedback via `append_feedback(...)` using that payload.
   - This is not strictly duplicate write logic in-stage, but feedback handling is split between stage and route (stage prepares, route persists).

## C) Stages/pipelines declared but never referenced

1. **Unused pipeline declarations in active YAML (`logos/knowledgebase/pipelines.yml`)**
   - `pipeline.reasoning_alerts` and `pipeline.concept_update` are declared but not invoked by any route/service run path.

2. **Unused workflow registry pipeline system**
   - `logos/knowledgebase/workflows/pipelines.yml` plus `logos.workflows.registry` execution path appears unused by current app endpoints.

## D) Learning hooks defined but never invoked (or effectively skipped)

### Effectively skipped due to missing context keys in route-provided contexts

1. **`sync_knowledgebase` in ingest flow (`nlp.extract` wrapper)**
   - Called every ingest run, but writes are skipped when `knowledgebase_path` is absent.
   - Current ingest route contexts do not set `knowledgebase_path`; therefore this hook usually no-ops after logging skip.

2. **`persist_session_memory` in commit flow (`learn.capture_feedback`)**
   - Called every commit run, but early-returns when `knowledgebase_path` is absent and no `knowledge_updater` provided.
   - Current commit route contexts do not include those keys.

3. **`S7_REFLECT_AND_LEARN` in commit flow**
   - Stage executes, but returns early with `reflect_and_learn_skip_no_kb` unless `knowledgebase_path` is provided.
   - Current commit route contexts omit this key; learning mutations are therefore typically not applied.

### Fully defined but not reached at all

4. **`pipeline.reasoning_alerts` learning/persistence behavior**
   - `R4_MATERIALISE_ALERTS` can upsert alert nodes/relationships and evolve schema store metadata.
   - Not invoked because `pipeline.reasoning_alerts` has no current runtime trigger.

---

## 5) Consolidated execution reality (current state)

- Ingest and commit runtime behavior is driven by `logos.core.pipeline_executor` + `logos/knowledgebase/pipelines.yml`.
- Alert retrieval endpoints currently query existing data directly; they do not run alert-generation pipelines.
- The commit pipeline contains declarative stages for alert evaluation and learning, but those are currently placeholder or context-gated and often non-mutating in default route wiring.
- A second pipeline framework (`logos.workflows.registry` + `logos/knowledgebase/workflows/pipelines.yml`) remains in the codebase but is not in active route execution paths.

