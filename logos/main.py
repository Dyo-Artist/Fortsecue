from fastapi import FastAPI, HTTPException

from .graphio.upsert import upsert_interaction
from .graphio.neo4j_client import run_query

app = FastAPI()
PREVIEW_CACHE: dict[str, str] = {}


@app.post("/commit/{interaction_id}")
async def commit(interaction_id: str) -> dict[str, str]:
    preview = PREVIEW_CACHE.get(interaction_id)
    if preview is None:
        raise HTTPException(status_code=404, detail="Preview not found")
    upsert_interaction(interaction_id, preview)
    return {"status": "committed"}


@app.get("/search")
async def search(q: str) -> list[dict[str, object]]:
    results = run_query(
        (
            "CALL db.index.fulltext.queryNodes('logos_name_idx', $q) "
            "YIELD node, score "
            "RETURN labels(node) AS labels, node.id AS id, node.name AS name, score "
            "ORDER BY score DESC LIMIT 10"
        ),
        {"q": q},
    )
    return [
        {
            "labels": r["labels"],
            "id": r["id"],
            "name": r["name"],
            "score": r["score"],
        }
        for r in results
    ]
