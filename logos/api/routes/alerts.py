"""Alert endpoints for LOGOS."""

from __future__ import annotations

from datetime import datetime, timezone
from math import ceil

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ...core.pipeline_executor import PipelineContext, PipelineStageError, run_pipeline
from ...graphio import queries as graph_queries
from ...graphio.neo4j_client import GraphUnavailable, get_client
from ...knowledgebase.store import KnowledgebaseStore
from ...reasoning.path_policy import record_alert_outcome

router = APIRouter()


class AlertOutcomeUpdate(BaseModel):
    status: str


def _run_reasoning_alerts() -> None:
    context = PipelineContext(
        context_data={
            "graph_client_factory": get_client,
        }
    )
    run_pipeline("pipeline.reasoning_alerts", {}, context)


def _parse_filters(raw_filters: list[str] | None) -> list[str]:
    if not raw_filters:
        return []
    parsed: list[str] = []
    for value in raw_filters:
        parsed.extend(part.strip() for part in value.split(",") if part.strip())
    return parsed


@router.get("/alerts")
async def list_alerts(
    type_filters: list[str] | None = Query(None, alias="type"),
    status_filters: list[str] | None = Query(None, alias="status"),
    project_id: str | None = Query(None),
    stakeholder_id: str | None = Query(None),
    org_id: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> dict[str, object]:
    types = _parse_filters(type_filters)
    statuses = _parse_filters(status_filters)
    try:
        _run_reasoning_alerts()
        items, total = graph_queries.list_alerts(
            types=types or None,
            statuses=statuses or None,
            project_id=project_id,
            stakeholder_id=stakeholder_id,
            org_id=org_id,
            page=page,
            page_size=page_size,
        )
    except PipelineStageError as exc:
        if isinstance(exc.cause, GraphUnavailable):
            return JSONResponse(status_code=503, content={"error": "neo4j_unavailable"})
        raise
    except GraphUnavailable:
        return JSONResponse(status_code=503, content={"error": "neo4j_unavailable"})
    total_pages = ceil(total / page_size) if page_size else 1
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total_items": total,
        "total_pages": total_pages,
    }


@router.patch("/alerts/{alert_id}/outcome")
async def update_alert_outcome(alert_id: str, payload: AlertOutcomeUpdate) -> dict[str, object]:
    new_status = payload.status.strip().lower()
    if new_status not in {"acknowledged", "closed", "ignored"}:
        return JSONResponse(status_code=400, content={"error": "invalid_status"})

    timestamp = datetime.now(timezone.utc).isoformat()
    rows = get_client().run(
        (
            "MATCH (a) "
            "WHERE any(label IN labels(a) WHERE toLower(label) CONTAINS 'alert') "
            "AND a.id = $alert_id "
            "SET a.status = $status, "
            "    a.outcome = $status, "
            "    a.outcome_at = datetime($timestamp), "
            "    a.last_updated_at = datetime($timestamp) "
            "RETURN a.id AS alert_id, "
            "       coalesce(a.path_features, a.scored_path.feature_vector, {}) AS path_features, "
            "       coalesce(a.model_score, a.risk_score, 0.0) AS model_score"
        ),
        {"alert_id": alert_id, "status": new_status, "timestamp": timestamp},
    )
    if not rows:
        return JSONResponse(status_code=404, content={"error": "not_found"})

    row = rows[0]
    logged, action = record_alert_outcome(
        alert_id=str(row.get("alert_id") or alert_id),
        outcome_status=new_status,
        model_score=float(row.get("model_score", 0.0) or 0.0),
        features=row.get("path_features") if isinstance(row.get("path_features"), dict) else {},
        timestamp=timestamp,
        kb_store=KnowledgebaseStore(),
        run_query=get_client().run,
    )

    return {
        "alert_id": alert_id,
        "status": new_status,
        "reinforcement_logged": logged,
        "retraining_action": action,
    }
