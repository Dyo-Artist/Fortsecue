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


@app.get("/graph/ego")
async def ego_graph(person_id: str) -> dict[str, list[dict[str, object]]]:
    results = run_query(
        (
            "MATCH (p:Person {id: $person_id}) "
            "OPTIONAL MATCH (p)-[r]-(n) "
            "WITH p, collect(r) AS rels, collect(n) AS ns "
            "RETURN "
            "[{id: p.id, name: p.name, labels: labels(p)}] AS pnodes, "
            "[x IN ns WHERE x IS NOT NULL | {id: x.id, name: x.name, labels: labels(x)}] AS nodes, "
            "[x IN rels WHERE x IS NOT NULL | {source: startNode(x).id, target: endNode(x).id, type: type(x)}] AS edges"
        ),
        {"person_id": person_id},
    )
    rows = list(results)
    row = rows[0] if rows else {"pnodes": [], "nodes": [], "edges": []}
    return {
        "pnodes": row.get("pnodes", []),
        "nodes": row.get("nodes", []),
        "edges": row.get("edges", []),
    }
