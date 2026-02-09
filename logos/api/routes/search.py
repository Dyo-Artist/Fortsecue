"""Search endpoints for LOGOS."""

from __future__ import annotations

from math import ceil

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from ...graphio.neo4j_client import GraphUnavailable
from ...graphio import queries as graph_queries

router = APIRouter()


def _parse_types(type_filters: list[str] | None) -> list[str]:
    if not type_filters:
        return []
    parsed: list[str] = []
    for value in type_filters:
        parsed.extend(part.strip() for part in value.split(",") if part.strip())
    return parsed


@router.get("/search")
async def search_api(
    q: str = Query(...),
    type_filters: list[str] | None = Query(None, alias="type"),
    org_id: str | None = Query(None),
    project_id: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> dict[str, object]:
    types = _parse_types(type_filters)
    try:
        labels = graph_queries.resolve_schema_labels(types)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        items, total = graph_queries.search_fulltext(
            q=q,
            labels=labels,
            org_id=org_id,
            project_id=project_id,
            page=page,
            page_size=page_size,
        )
    except GraphUnavailable:
        return JSONResponse(status_code=503, content={"error": "neo4j_unavailable"})

    response_items: list[dict[str, object]] = []
    for item in items:
        labels_list = item.get("labels", [])
        props = item.get("props", {})
        score = item.get("score")
        label = graph_queries.pick_entity_label(labels_list, labels)
        entity_type = label.lower() if label else "entity"
        response_items.append(
            {"entity_type": entity_type, "score": score, entity_type: props}
        )

    total_pages = ceil(total / page_size) if page_size else 1
    return {
        "items": response_items,
        "page": page,
        "page_size": page_size,
        "total_items": total,
        "total_pages": total_pages,
    }
