# LOGOS

Local-first stakeholder intelligence for ingesting interactions, previewing extracted entities/relationships, committing them to Neo4j, and exploring via search, graph views, and alerts.

The current MVP flows an interaction through ingest → preview → commit → search/graph/alerts so teams can rapidly map people, organisations, projects, contracts, and commitments.

## Requirements
- Python 3.11+
- Neo4j 4.x/5.x reachable locally or remotely

## Installation
```bash
git clone <REPO_URL>
cd <REPO_DIR>
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate
pip install -r requirements.txt
```

## Configure Neo4j
LOGOS reads connection details from environment variables:

```bash
export NEO4J_URI="bolt://localhost:7687"
export NEO4J_USER="neo4j"
export NEO4J_PASSWORD="your-password"
# optional:
# export NEO4J_DATABASE="neo4j"
```

## Configure staging path
Staging artefacts (raw inputs, previews, and the staging index) are stored locally. Override the default location with `LOGOS_STAGING_DIR`:

```bash
export LOGOS_STAGING_DIR="$PWD/.logos/staging"
```

## Configure model tiers
Model selection is driven by `logos/knowledgebase/models/tiers.yml` and supports `rule_only`, `local_ml`, and `local_llm` per task. Update the YAML file to switch tiers; for example, set `extraction_interaction` to `local_llm` to use a local LLM for extraction. Optional Ollama settings remain environment-driven:

```bash
# Only if you have Ollama and a local model configured:
export OLLAMA_URL="http://localhost:11434/api/generate"
export OLLAMA_MODEL="gpt-oss:20b"
```

## Running the app
```bash
uvicorn logos.main:app --reload --host 0.0.0.0 --port 8000
```

## Developer smoke preview
Run a lightweight ingest → preview check locally (defaults start a FastAPI instance on port 8000):

```bash
python scripts/dev_smoke_preview.py
```

Use `--no-start` if you already have the app running, and `--text` to try a different note:

```bash
python scripts/dev_smoke_preview.py --no-start --text "Maria will share the Q4 budget draft with the project team tomorrow."
```

Expected output:

```
Smoke test preview ready
Interaction ID: <generated-id>
Summary: <extracted summary or note text>
Persons: <count>
Organisations: <count>
Commitments: <count>
```

## Using the app
- Visit `http://localhost:8000/`:
  - Use “Ingest Document” or “Ingest Note” to create a preview.
  - Inspect the JSON preview in the “Last Preview” panel.
  - Note the `interaction_id` in the JSON.
- Commit the interaction:
  - Use `POST /commit/{interaction_id}` from:
    - the automatically generated docs at `http://localhost:8000/docs`, or
    - curl / HTTP client.
- Explore graph data:
  - Use the HTML UI sections for:
    - Search,
    - Ego Graph (Person),
    - Project Map,
    - Alerts.
  - Or call the JSON endpoints: `/search`, `/graph/ego`, `/graph/project`, `/alerts`.

## Testing
```bash
pytest -q
```

LOGOS runs completely without Ollama; enabling Ollama is optional and local-only.
