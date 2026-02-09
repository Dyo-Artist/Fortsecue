"""Alert endpoints for LOGOS."""

from __future__ import annotations

from math import ceil

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from ...graphio import queries as graph_queries
from ...graphio.neo4j_client import GraphUnavailable

router = APIRouter()


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
        items, total = graph_queries.list_alerts(
            types=types or None,
            statuses=statuses or None,
            project_id=project_id,
            stakeholder_id=stakeholder_id,
            org_id=org_id,
            page=page,
            page_size=page_size,
        )
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
