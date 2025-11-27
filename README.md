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

## Optional: Ollama integration
LOGOS runs fully without Ollama (default regex NLP). Ollama is an optional local enhancement path:

```bash
# Only if you have Ollama and a local model configured:
export LOGOS_USE_OLLAMA=1
# optional overrides:
# export OLLAMA_URL="http://localhost:11434/api/generate"
# export OLLAMA_MODEL="gpt-oss:20b"
```

## Running the app
```bash
uvicorn logos.main:app --reload --host 0.0.0.0 --port 8000
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
