# This module is part of LOGOS (local-first stakeholder intelligence).
# It must follow the architecture and schema defined in the LOGOS docs (/docs).
# Pipeline: ingest → transcribe → nlp_extract → normalise → graphio → ui.
from datetime import datetime, timezone
from uuid import uuid4
from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .graphio.upsert import (
    upsert_commitment,
    upsert_contract,
    upsert_interaction,
    upsert_org,
    upsert_person,
    upsert_project,
    upsert_relationship,
    upsert_topic,
)
from .graphio.neo4j_client import GraphUnavailable, ping, run_query
from .ingest import doc_ingest
from .interfaces.local_asr_stub import TranscriptionFailure, transcribe
from .nlp.extract import extract_all

app = FastAPI()
PENDING_INTERACTIONS: Dict[str, Dict[str, Any]] = {}
# PREVIEWS is kept for backwards compatibility with existing callers/tests.
PREVIEWS = PENDING_INTERACTIONS


class Doc(BaseModel):
    source_uri: str
    text: str


class AudioPayload(BaseModel):
    source_uri: str = ""


def _build_interaction_metadata(type_: str, source_uri: str, at: datetime | None = None) -> Dict[str, Any]:
    return {
        "type": type_,
        "at": (at or datetime.now(timezone.utc)).isoformat(),
        "source_uri": source_uri,
    }


def _persist_preview(interaction_id: str, interaction_meta: Dict[str, Any], extraction: Dict[str, Any]) -> Dict[str, Any]:
    preview = {
        "interaction": {
            "id": interaction_id,
            **interaction_meta,
            "sentiment": extraction.get("sentiment"),
            "summary": extraction.get("summary"),
        },
        "entities": extraction.get("entities", {}),
        "relationships": extraction.get("relationships", []),
    }
    PENDING_INTERACTIONS[interaction_id] = preview
    return preview


def _normalise_entity_list(
    entries: list[Any],
    *,
    id_fallbacks: tuple[str, ...] = ("id",),
    name_field: str = "name",
) -> list[dict[str, Any]]:
    normalised: list[dict[str, Any]] = []
    for entry in entries:
        if isinstance(entry, str):
            normalised.append({"id": entry, name_field: entry})
            continue
        if isinstance(entry, dict):
            entity_id = next((entry.get(key) for key in id_fallbacks if entry.get(key)), None)
            if not entity_id:
                continue
            record = dict(entry)
            record["id"] = entity_id
            if name_field not in record and entry.get("name"):
                record[name_field] = entry["name"]
            if name_field not in record and entry.get("text") and name_field != "text":
                record[name_field] = entry["text"]
            if name_field not in record:
                record[name_field] = entity_id
            normalised.append(record)
    return normalised


def _label_index(interaction_id: str, entities: dict[str, list[dict[str, Any]]]) -> dict[str, str]:
    labels = {interaction_id: "Interaction"}
    for label, key in [
        ("Org", "orgs"),
        ("Person", "persons"),
        ("Project", "projects"),
        ("Contract", "contracts"),
        ("Topic", "topics"),
        ("Commitment", "commitments"),
    ]:
        for item in entities.get(key, []):
            if item.get("id"):
                labels[item["id"]] = label
    return labels


def _commit_entities(interaction_id: str, preview: Dict[str, Any]) -> None:
    interaction = preview.get("interaction", {})
    interaction_id = interaction.get("id") or interaction_id
    entities_raw = preview.get("entities", {})

    entities = {
        "orgs": _normalise_entity_list(entities_raw.get("orgs", []), name_field="name"),
        "persons": _normalise_entity_list(
            entities_raw.get("persons", []), name_field="name"
        ),
        "projects": _normalise_entity_list(
            entities_raw.get("projects", []), name_field="name"
        ),
        "contracts": _normalise_entity_list(
            entities_raw.get("contracts", []), name_field="name"
        ),
        "topics": _normalise_entity_list(entities_raw.get("topics", []), name_field="name"),
        "commitments": _normalise_entity_list(
            entities_raw.get("commitments", []), id_fallbacks=("id", "text"), name_field="text"
        ),
    }

    for org in entities["orgs"]:
        upsert_org(org["id"], org.get("name", org["id"]))

    for person in entities["persons"]:
        upsert_person(person["id"], person.get("name", person["id"]), org_id=person.get("org_id"))

    for project in entities["projects"]:
        upsert_project(project["id"], project.get("name", project["id"]), status=project.get("status"))

    for contract in entities["contracts"]:
        upsert_contract(
            contract["id"],
            contract.get("name", contract["id"]),
            sap_id=contract.get("sap_id"),
            value=contract.get("value"),
            start_date=contract.get("start_date"),
            end_date=contract.get("end_date"),
        )

    for topic in entities["topics"]:
        upsert_topic(topic["id"], topic.get("name", topic["id"]))

    for commitment in entities["commitments"]:
        if not commitment.get("person_id"):
            continue
        upsert_commitment(
            commitment["id"],
            commitment.get("text", commitment["id"]),
            commitment["person_id"],
            due_date=commitment.get("due_date"),
            status=commitment.get("status", "open"),
            relates_to_project_id=commitment.get("relates_to_project_id"),
            relates_to_contract_id=commitment.get("relates_to_contract_id"),
        )

    mention_person_ids = None
    relationships = preview.get("relationships", [])
    if relationships:
        mention_person_ids = {
            rel.get("dst")
            for rel in relationships
            if rel.get("rel") == "MENTIONS" and rel.get("dst")
        }
        if mention_person_ids:
            mention_person_ids = list(mention_person_ids)

    upsert_interaction(
        interaction_id,
        interaction.get("type", ""),
        interaction.get("at", datetime.now(timezone.utc).isoformat()),
        interaction.get("sentiment", 0.0),
        interaction.get("summary", ""),
        interaction.get("source_uri", ""),
        mention_person_ids,
    )

    labels = _label_index(interaction_id, entities)
    for rel in relationships:
        src = rel.get("src")
        dst = rel.get("dst")
        rel_type = rel.get("rel")
        if not src or not dst or not rel_type:
            continue
        upsert_relationship(
            src,
            dst,
            rel_type,
            src_label=labels.get(src),
            dst_label=labels.get(dst),
            properties={k: v for k, v in rel.items() if k not in {"src", "dst", "rel"}},
        )


@app.post("/ingest/doc")
async def ingest_doc(doc: Doc) -> dict[str, object]:
    """Ingest plain text documents and return an interaction id."""
    interaction_stub, raw_text = doc_ingest(doc.model_dump())
    extraction = extract_all(raw_text)
    interaction_id = uuid4().hex
    metadata = _build_interaction_metadata(
        type_=interaction_stub.get("type", "document"),
        source_uri=interaction_stub.get("source_uri", doc.source_uri),
        at=interaction_stub.get("at"),
    )
    preview = _persist_preview(interaction_id, metadata, extraction)
    return {"interaction_id": interaction_id, "preview": preview}


@app.post("/ingest/audio")
async def ingest_audio(payload: AudioPayload) -> dict[str, object]:
    try:
        transcript = transcribe(payload.source_uri)
    except TranscriptionFailure as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    text = transcript.get("text")
    if not text:
        raise HTTPException(status_code=502, detail="Transcription failed")

    extraction = extract_all(text)
    interaction_id = uuid4().hex
    metadata = _build_interaction_metadata("audio", payload.source_uri)
    preview = _persist_preview(interaction_id, metadata, extraction)
    return {"interaction_id": interaction_id, "preview": preview}


@app.post("/commit/{interaction_id}")
async def commit_interaction(interaction_id: str) -> dict[str, str]:
    preview = PENDING_INTERACTIONS.get(interaction_id)
    if preview is None:
        raise HTTPException(status_code=404, detail="interaction not found")

    try:
        _commit_entities(interaction_id, preview)
    except GraphUnavailable:
        return JSONResponse(status_code=503, content={"error": "neo4j_unavailable"})

    PENDING_INTERACTIONS.pop(interaction_id, None)
    return {"status": "committed", "interaction_id": interaction_id}


@app.get("/health")
async def health() -> dict[str, str]:
    try:
        status = ping()
    except GraphUnavailable:
        return {"neo4j": "down", "reason": "neo4j_unavailable"}

    if not status.get("ok"):
        return {"neo4j": "down", "reason": status.get("reason", "neo4j_unavailable")}
    return {"neo4j": "ok"}


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
