from uuid import uuid4

from fastapi import FastAPI, HTTPException, UploadFile, File

from .graphio.upsert import upsert_interaction
from .graphio.neo4j_client import run_query

app = FastAPI()
PREVIEW_CACHE: dict[str, str] = {}


def _store_preview(preview: str) -> dict[str, str]:
    """Store preview text and return a new interaction id."""
    interaction_id = str(uuid4())
    PREVIEW_CACHE[interaction_id] = preview
    return {"interaction_id": interaction_id, "preview": preview}


@app.post("/ingest/audio")
async def ingest_audio(file: UploadFile = File(...)) -> dict[str, str]:
    if not file.content_type.startswith("audio/"):
        raise HTTPException(status_code=400, detail="Invalid audio type")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    preview = "transcribed"
    return _store_preview(preview)


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


@app.get("/alerts")
async def alerts() -> dict[str, list[dict[str, object]]]:
    unresolved_results = run_query(
        (
            "MATCH (c:Commitment)<-[:MADE]-(p:Person) "
            "WHERE c.status NOT IN ['accepted', 'done'] "
            "AND c.due_date < date() - duration('P7D') "
            "RETURN c.id AS id, c.description AS description, "
            "c.due_date AS due_date, c.status AS status, "
            "p.id AS person_id, p.name AS person_name"
        )
    )
    unresolved = [
        {
            "id": r["id"],
            "description": r.get("description"),
            "due_date": r.get("due_date"),
            "status": r.get("status"),
            "person_id": r.get("person_id"),
            "person_name": r.get("person_name"),
        }
        for r in unresolved_results
    ]

    sentiment_results = run_query(
        (
            "MATCH (o:Org)<-[:WORKS_FOR]-(p:Person)<-[:MENTIONS]-(i:Interaction) "
            "WHERE i.date >= date() - duration('P14D') "
            "WITH o, i ORDER BY i.date DESC "
            "WITH o, collect(i.sentiment)[0..3] AS last3 "
            "WHERE size(last3) = 3 AND all(s IN last3 WHERE s = 'negative') "
            "RETURN o.id AS org_id, o.name AS org_name"
        )
    )
    sentiment = [
        {"org_id": r["org_id"], "org_name": r["org_name"]}
        for r in sentiment_results
    ]

    return {
        "unresolved_commitments": unresolved,
        "sentiment_drop": sentiment,
    }
