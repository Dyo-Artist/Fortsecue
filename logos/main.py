# This module is part of LOGOS (local-first stakeholder intelligence).
# It must follow the architecture and schema defined in the LOGOS docs (/docs).
# Pipeline: ingest → transcribe → nlp_extract → normalise → graphio → ui.
import logging
import os
from datetime import datetime, timezone
from uuid import uuid4
from typing import Any, Dict, Mapping
import pathlib

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from .core.pipeline_executor import PipelineContext, PipelineStageError, run_pipeline
from .graphio import graph_views
from .graphio import search as search_module
from .graphio.graph_views import ego_network, project_map
from .graphio.search import search_entities
from .graphio.neo4j_client import GraphUnavailable, get_client, ping, run_query
from .interfaces.local_asr_stub import TranscriptionFailure, transcribe
from .models.bundles import InteractionMeta, PreviewBundle, RawInputBundle
from .services.sync import build_graph_update_event, update_broadcaster
from .staging.store import LocalStagingStore

app = FastAPI()
templates = Jinja2Templates(
    directory=str(pathlib.Path(__file__).resolve().parent / "templates")
)
PENDING_INTERACTIONS: Dict[str, Dict[str, Any]] = {}
# PREVIEWS is kept for backwards compatibility with existing callers/tests.
PREVIEWS = PENDING_INTERACTIONS
STAGING_STORE = LocalStagingStore(os.getenv("LOGOS_STAGING_DIR"))
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


@app.websocket("/ws/updates")
async def updates(websocket: WebSocket) -> None:
    await update_broadcaster.register(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await update_broadcaster.unregister(websocket)


@app.post("/ingest/doc")
async def ingest_doc(doc: Doc) -> dict[str, object]:
    """Ingest plain text documents and return an interaction id."""
    interaction_id = uuid4().hex
    meta = InteractionMeta(
        interaction_id=interaction_id,
        interaction_type="document",
        source_uri=doc.source_uri,
        source_type="doc",
        created_by="api",
    )
    meta = STAGING_STORE.create_interaction(meta)
    STAGING_STORE.save_raw_text(interaction_id, doc.text)
    raw_bundle = RawInputBundle(meta=meta, raw_text=doc.text, metadata={"type": "document"})
    context = PipelineContext(
        request_id=interaction_id,
        user_id="api",
        context_data={
            "interaction_id": interaction_id,
            "interaction_type": "document",
            "source_uri": doc.source_uri,
            "staging_store": STAGING_STORE,
            "pending_interactions": PENDING_INTERACTIONS,
        },
    )
    try:
        preview = run_pipeline("pipeline.interaction_ingest", raw_bundle, context)
    except Exception as exc:
        STAGING_STORE.set_state(interaction_id, "failed", error_message=str(exc))
        logger.exception("doc_ingest_failed", extra={"interaction_id": interaction_id})
        raise
    preview_payload = (
        preview.model_dump(mode="json") if isinstance(preview, PreviewBundle) else preview
    )
    return {"interaction_id": interaction_id, "preview_ready": True, "preview": preview_payload}


@app.post("/ingest/note")
async def ingest_note(note: Note) -> dict[str, object]:
    interaction_id = uuid4().hex
    meta = InteractionMeta(
        interaction_id=interaction_id,
        interaction_type="note",
        source_uri=note.source_uri or "",
        source_type="text",
        created_by="api",
    )
    meta = STAGING_STORE.create_interaction(meta)
    STAGING_STORE.save_raw_text(interaction_id, note.text)
    raw_bundle = RawInputBundle(
        meta=meta,
        raw_text=note.text,
        metadata={"type": "note", "topic": note.topic} if note.topic else {"type": "note"},
    )
    context = PipelineContext(
        request_id=interaction_id,
        user_id="api",
        context_data={
            "interaction_id": interaction_id,
            "interaction_type": "note",
            "source_uri": note.source_uri or "",
            "staging_store": STAGING_STORE,
            "pending_interactions": PENDING_INTERACTIONS,
        },
    )
    try:
        preview = run_pipeline("pipeline.interaction_ingest", raw_bundle, context)
    except Exception as exc:
        STAGING_STORE.set_state(interaction_id, "failed", error_message=str(exc))
        logger.exception("note_ingest_failed", extra={"interaction_id": interaction_id})
        raise
    preview_payload = (
        preview.model_dump(mode="json") if isinstance(preview, PreviewBundle) else preview
    )
    return {"interaction_id": interaction_id, "preview_ready": True, "preview": preview_payload}


@app.post("/api/v1/ingest/text")
async def ingest_text_api(note: Note) -> dict[str, object]:
    """Versioned alias for note ingestion used by tooling and docs."""

    return await ingest_note(note)


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
    meta = InteractionMeta(
        interaction_id=interaction_id,
        interaction_type="audio",
        source_uri=payload.source_uri,
        source_type="audio",
        created_by="api",
    )
    meta = STAGING_STORE.create_interaction(meta)
    STAGING_STORE.save_raw_text(interaction_id, text)
    raw_bundle = RawInputBundle(meta=meta, raw_text=text, metadata={"type": "audio"})
    context = PipelineContext(
        request_id=interaction_id,
        user_id="api",
        context_data={
            "interaction_id": interaction_id,
            "interaction_type": "audio",
            "source_uri": payload.source_uri,
            "staging_store": STAGING_STORE,
            "pending_interactions": PENDING_INTERACTIONS,
        },
    )
    try:
        preview = run_pipeline("pipeline.interaction_ingest", raw_bundle, context)
    except Exception as exc:
        STAGING_STORE.set_state(interaction_id, "failed", error_message=str(exc))
        logger.exception("audio_ingest_failed", extra={"interaction_id": interaction_id})
        raise
    preview_payload = (
        preview.model_dump(mode="json") if isinstance(preview, PreviewBundle) else preview
    )
    return {"interaction_id": interaction_id, "preview_ready": True, "preview": preview_payload}


@app.get("/api/v1/interactions/{interaction_id}/preview")
async def get_interaction_preview(interaction_id: str) -> dict[str, object]:
    try:
        preview = STAGING_STORE.get_preview(interaction_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="preview_not_found") from None

    return preview.model_dump()


@app.get("/api/v1/interactions/{interaction_id}/status")
async def get_interaction_status(interaction_id: str) -> dict[str, object]:
    try:
        state = STAGING_STORE.get_state(interaction_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="interaction_not_found") from None

    return {
        "interaction_id": state.interaction_id,
        "state": state.state,
        "received_at": state.received_at.isoformat(),
        "updated_at": state.updated_at.isoformat(),
        "error_message": state.error_message,
    }


@app.post("/commit/{interaction_id}")
async def commit_interaction(interaction_id: str) -> dict[str, object]:
    preview = PENDING_INTERACTIONS.get(interaction_id)
    if preview is None:
        try:
            preview = STAGING_STORE.get_preview(interaction_id).model_dump()
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="interaction not found") from None

    try:
        context = PipelineContext(
            request_id=interaction_id,
            user_id="api",
            context_data={
                "interaction_id": interaction_id,
                "graph_client_factory": get_client,
                "commit_time": datetime.now(timezone.utc),
                "graph_update_builder": build_graph_update_event,
            },
        )
        summary = run_pipeline("pipeline.interaction_commit", preview, context)
    except PipelineStageError as exc:
        if isinstance(exc.cause, GraphUnavailable):
            return JSONResponse(status_code=503, content={"error": "neo4j_unavailable"})
        STAGING_STORE.set_state(interaction_id, "failed", error_message=str(exc))
        raise
    except GraphUnavailable:
        STAGING_STORE.set_state(interaction_id, "failed", error_message="neo4j_unavailable")
        return JSONResponse(status_code=503, content={"error": "neo4j_unavailable"})
    except Exception:
        logger.exception("Failed to commit interaction %s", interaction_id)
        STAGING_STORE.set_state(interaction_id, "failed", error_message="commit_failed")
        raise HTTPException(status_code=500, detail="commit_failed")

    graph_updates = context.context_data.get("graph_updates", [])
    for update in graph_updates:
        try:
            await update_broadcaster.broadcast(update)
        except Exception:  # pragma: no cover - defensive guard to avoid failing commit responses
            logger.exception("Failed to broadcast graph update for interaction %s", interaction_id)

    PENDING_INTERACTIONS.pop(interaction_id, None)
    STAGING_STORE.set_state(interaction_id, "committed")
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
