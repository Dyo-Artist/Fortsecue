# This module is part of LOGOS (local-first stakeholder intelligence).
# It must follow the architecture and schema defined in the LOGOS docs (/docs).
# Pipeline: ingest → transcribe → nlp_extract → normalise → graphio → ui.
from datetime import datetime
from uuid import uuid4
import re

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .graphio.upsert import upsert_interaction
from .graphio.neo4j_client import GraphUnavailable, ping, run_query
from .services.transcription import TranscriptionError, transcribe_audio

app = FastAPI()
PREVIEWS: dict[str, dict[str, object]] = {}


def _extract_entities(text: str) -> dict[str, list[str]]:
    """Extract simple entities from text."""
    person_pattern = re.compile(r"\b([A-Z][a-z]+ [A-Z][a-z]+)\b")
    org_pattern = re.compile(
        r"\b([A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*)*\s+(?:Pty Ltd|Pty|Ltd|LLC|Inc|Corporation|Corp|Company))\b"
    )
    commitment_pattern = re.compile(
        r"\b(?:will|shall)\b[^.]*?\bby\s+[^\.\n]+", re.IGNORECASE
    )
    persons = person_pattern.findall(text)
    orgs = org_pattern.findall(text)
    commitments = commitment_pattern.findall(text)
    return {
        "persons": persons,
        "orgs": orgs,
        "commitments": commitments,
        "projects": [],
    }


def _store_preview(text: str, source_uri: str) -> dict[str, object]:
    """Build and store preview for the given text."""
    interaction_id = str(uuid4())
    entities = _extract_entities(text)
    preview = {
        "entities": entities,
        "relationships": [],
        "interaction": {
            "id": interaction_id,
            "type": "document",
            "at": datetime.utcnow().isoformat(),
            "sentiment": 0.0,
            "summary": text[:140],
            "source_uri": source_uri,
        },
    }
    PREVIEWS[interaction_id] = preview
    return {"interaction_id": interaction_id, "preview": preview}


class Doc(BaseModel):
    source_uri: str
    text: str


@app.post("/ingest/doc")
async def ingest_doc(doc: Doc) -> dict[str, object]:
    """Ingest plain text documents and return an interaction id."""
    return _store_preview(doc.text, doc.source_uri)


@app.post("/ingest/audio")
async def ingest_audio(file: UploadFile = File(...)) -> dict[str, object]:
    if not file.content_type.startswith("audio/"):
        raise HTTPException(status_code=400, detail="Invalid audio type")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    try:
        transcript = await transcribe_audio(data, file.content_type)
    except TranscriptionError as exc:
        raise HTTPException(status_code=502, detail="Transcription failed") from exc
    source_uri = file.filename or ""
    return _store_preview(transcript, source_uri)


@app.post("/commit/{interaction_id}")
async def commit(interaction_id: str) -> dict[str, str]:
    preview = PREVIEWS.get(interaction_id)
    if preview is None:
        raise HTTPException(status_code=404, detail="Preview not found")
    interaction = preview["interaction"]
    try:
        upsert_interaction(
            interaction_id,
            interaction["type"],
            interaction["at"],
            interaction["sentiment"],
            interaction["summary"],
            interaction["source_uri"],
        )
    except GraphUnavailable:
        return JSONResponse(status_code=503, content={"error": "neo4j_unavailable"})
    return {"status": "committed"}


@app.get("/search")
async def search(q: str) -> list[dict[str, object]]:
    try:
        results = run_query(
            (
                "CALL db.index.fulltext.queryNodes('logos_name_idx', $q) "
                "YIELD node, score "
                "RETURN labels(node) AS labels, node{.*} AS props, score "
                "ORDER BY score DESC LIMIT 10"
            ),
            {"q": q},
        )
    except GraphUnavailable:
        return JSONResponse(status_code=503, content={"error": "neo4j_unavailable"})
    return [
        {**r["props"], "labels": r["labels"], "_score": r["score"]}
        for r in results
    ]


@app.get("/graph/ego")
async def ego_graph(person_id: str) -> dict[str, list[dict[str, object]]]:
    try:
        results = run_query(
            (
                "MATCH (p:Person {id: $person_id}) "
                "OPTIONAL MATCH (p)-[r]-(n) "
                "WITH p, collect(r) AS rels, collect(n) AS ns "
                "RETURN "
                "[{id: p.id, name: p.name, labels: labels(p)}] AS pnodes, "
                "[x IN ns WHERE x IS NOT NULL | {id: x.id, name: x.name, labels: labels(x)}] AS nodes, "
                "[x IN rels WHERE x IS NOT NULL | {src: startNode(x).id, dst: endNode(x).id, rel: type(x)}] AS edges"
            ),
            {"person_id": person_id},
        )
    except GraphUnavailable:
        return JSONResponse(status_code=503, content={"error": "neo4j_unavailable"})
    rows = list(results)
    row = rows[0] if rows else {"pnodes": [], "nodes": [], "edges": []}
    return {
        "pnodes": row.get("pnodes", []),
        "nodes": row.get("nodes", []),
        "edges": row.get("edges", []),
    }


@app.get("/alerts")
async def alerts() -> dict[str, list[dict[str, object]]]:
    try:
        unresolved_results = run_query(
            (
                "MATCH (c:Commitment)<-[:MADE]-(p:Person) "
                "WHERE c.status NOT IN ['accepted', 'done'] "
                "AND c.due_date < date() - duration('P7D') "
                "RETURN c.id AS id, c.text AS text, "
                "c.due_date AS due_date, c.status AS status, "
                "p.id AS person_id, p.name AS person_name"
            )
        )
    except GraphUnavailable:
        return JSONResponse(status_code=503, content={"error": "neo4j_unavailable"})
    unresolved = [
        {
            "id": r["id"],
            "text": r.get("text"),
            "due_date": r.get("due_date"),
            "status": r.get("status"),
            "person_id": r.get("person_id"),
            "person_name": r.get("person_name"),
        }
        for r in unresolved_results
    ]

    try:
        sentiment_results = run_query(
            (
                "MATCH (o:Org)<-[:WORKS_FOR]-(p:Person)<-[:MENTIONS]-(i:Interaction) "
                "WHERE i.at >= datetime() - duration('P14D') "
                "WITH o, i ORDER BY i.at DESC "
                "WITH o, collect(i.sentiment)[0..3] AS last3 "
                "WHERE size(last3) = 3 AND all(s IN last3 WHERE s = 'negative') "
                "RETURN o.id AS org_id, o.name AS org_name"
            )
        )
    except GraphUnavailable:
        return JSONResponse(status_code=503, content={"error": "neo4j_unavailable"})
    sentiment = [
        {"org_id": r["org_id"], "org_name": r["org_name"]}
        for r in sentiment_results
    ]

    return {
        "unresolved_commitments": unresolved,
        "sentiment_drop": sentiment,
    }


@app.get("/health")
async def health() -> dict[str, str]:
    status = ping()
    return {
        "neo4j": "up" if status["ok"] else "down",
        "reason": status["reason"],
    }
