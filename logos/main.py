# This module is part of LOGOS (local-first stakeholder intelligence).
# It must follow the architecture and schema defined in the LOGOS docs (/docs).
# Pipeline: ingest → transcribe → nlp_extract → normalise → graphio → ui.
from datetime import datetime, timezone
from uuid import uuid4
import logging
from typing import Any, Dict
import pathlib

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from .graphio import graph_views
from .graphio import search as search_module
from .graphio.graph_views import ego_network, project_map
from .graphio.search import search_entities
from .graphio.neo4j_client import GraphUnavailable, get_client, ping, run_query
from .interfaces.local_asr_stub import TranscriptionFailure, transcribe
from .workflows import RawInputBundle, run_pipeline

app = FastAPI()
templates = Jinja2Templates(
    directory=str(pathlib.Path(__file__).resolve().parent / "templates")
)
PENDING_INTERACTIONS: Dict[str, Dict[str, Any]] = {}
# PREVIEWS is kept for backwards compatibility with existing callers/tests.
PREVIEWS = PENDING_INTERACTIONS
logger = logging.getLogger(__name__)


class Doc(BaseModel):
    source_uri: str
    text: str


class Note(BaseModel):
    text: str
    source_uri: str | None = None
    topic: str | None = None


class AudioPayload(BaseModel):
    source_uri: str = ""


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


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


@app.post("/ingest/doc")
async def ingest_doc(doc: Doc) -> dict[str, object]:
    """Ingest plain text documents and return an interaction id."""
    interaction_id = uuid4().hex
    raw_bundle = RawInputBundle(
        text=doc.text, source_uri=doc.source_uri, metadata={"type": "document"}
    )
    context = {
        "interaction_id": interaction_id,
        "interaction_type": "document",
        "source_uri": doc.source_uri,
        "persist_preview": _persist_preview,
    }
    preview = run_pipeline("ingest_preview", raw_bundle, context)
    return {"interaction_id": interaction_id, "preview": preview}


@app.post("/ingest/note")
async def ingest_note(note: Note) -> dict[str, object]:
    interaction_id = uuid4().hex
    raw_bundle = RawInputBundle(
        text=note.text,
        source_uri=note.source_uri or "",
        metadata={"type": "note", "topic": note.topic} if note.topic else {"type": "note"},
    )
    context = {
        "interaction_id": interaction_id,
        "interaction_type": "note",
        "source_uri": note.source_uri or "",
        "persist_preview": _persist_preview,
    }
    preview = run_pipeline("ingest_preview", raw_bundle, context)
    return {"interaction_id": interaction_id, "preview": preview}


@app.post("/ui/ingest/doc")
async def ui_ingest_doc(request: Request):
    form = await request.form()
    payload = {
        "source_uri": form.get("source_uri") or "",
        "text": form.get("text") or "",
    }
    doc = Doc(**payload)
    result = await ingest_doc(doc)
    return templates.TemplateResponse(
        "index.html", {"request": request, "last_action": "doc", "result": result}
    )


@app.post("/ui/ingest/note")
async def ui_ingest_note(request: Request):
    form = await request.form()
    payload = {
        "text": form.get("text") or "",
        "source_uri": form.get("source_uri") or None,
    }
    note = Note(**payload)
    result = await ingest_note(note)
    return templates.TemplateResponse(
        "index.html", {"request": request, "last_action": "note", "result": result}
    )


@app.post("/ui/search")
async def ui_search(request: Request):
    form = await request.form()
    q = form.get("q") or ""
    result = await search(q=q)
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "last_action": "search", "result": result},
    )


@app.post("/ui/graph/ego")
async def ui_ego_graph(request: Request):
    form = await request.form()
    person_id = form.get("person_id") or ""
    result = await ego_graph(person_id=person_id)
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "last_action": "ego", "result": result},
    )


@app.post("/ui/graph/project")
async def ui_project_graph(request: Request):
    form = await request.form()
    project_id = form.get("project_id") or ""
    result = await project_graph(project_id=project_id)
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "last_action": "project", "result": result},
    )


@app.post("/ui/alerts")
async def ui_alerts(request: Request):
    result = await alerts()
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "last_action": "alerts", "result": result},
    )


@app.post("/ingest/audio")
async def ingest_audio(payload: AudioPayload) -> dict[str, object]:
    try:
        transcript = transcribe(payload.source_uri)
    except TranscriptionFailure as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    text = transcript.get("text")
    if not text:
        raise HTTPException(status_code=502, detail="Transcription failed")

    interaction_id = uuid4().hex
    raw_bundle = RawInputBundle(
        text=text, source_uri=payload.source_uri, metadata={"type": "audio"}
    )
    context = {
        "interaction_id": interaction_id,
        "interaction_type": "audio",
        "source_uri": payload.source_uri,
        "persist_preview": _persist_preview,
    }
    preview = run_pipeline("ingest_preview", raw_bundle, context)
    return {"interaction_id": interaction_id, "preview": preview}


@app.post("/commit/{interaction_id}")
async def commit_interaction(interaction_id: str) -> dict[str, object]:
    preview = PENDING_INTERACTIONS.get(interaction_id)
    if preview is None:
        raise HTTPException(status_code=404, detail="interaction not found")

    try:
        context = {
            "interaction_id": interaction_id,
            "graph_client_factory": get_client,
            "commit_time": datetime.now(timezone.utc),
        }
        summary = run_pipeline("commit_interaction", preview, context)
    except GraphUnavailable:
        return JSONResponse(status_code=503, content={"error": "neo4j_unavailable"})
    except Exception:
        logger.exception("Failed to commit interaction %s", interaction_id)
        raise HTTPException(status_code=500, detail="commit_failed")

    PENDING_INTERACTIONS.pop(interaction_id, None)
    return summary


# Reports Neo4j availability using graphio.neo4j_client.ping().
# Returns {"neo4j": "ok"} when reachable or {"neo4j": "down", "reason": "..."}.
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
        search_module.run_query = run_query
        return search_entities(q)
    except GraphUnavailable:
        return JSONResponse(status_code=503, content={"error": "neo4j_unavailable"})


@app.get("/graph/ego")
async def ego_graph(person_id: str) -> dict[str, list[dict[str, object]]]:
    try:
        graph_views.run_query = run_query
        network = ego_network(person_id)
        if "pnodes" not in network:
            pnodes = [
                node for node in network.get("nodes", []) if node.get("id") == person_id
            ]
            network = {"pnodes": pnodes, **network}
        return network
    except GraphUnavailable:
        return JSONResponse(status_code=503, content={"error": "neo4j_unavailable"})


@app.get("/graph/project")
async def project_graph(project_id: str) -> dict[str, list[dict[str, object]]]:
    try:
        graph_views.run_query = run_query
        return project_map(project_id)
    except GraphUnavailable:
        return JSONResponse(status_code=503, content={"error": "neo4j_unavailable"})


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
