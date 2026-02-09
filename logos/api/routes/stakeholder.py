"""Stakeholder 360 endpoints for LOGOS."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from ...graphio.neo4j_client import GraphUnavailable
from ...graphio import queries as graph_queries

router = APIRouter()


@router.get("/stakeholders/{stakeholder_id}")
async def stakeholder_view(
    stakeholder_id: str,
    from_date: str | None = Query(None, alias="from"),
    to_date: str | None = Query(None, alias="to"),
    include_graph: bool = Query(False),
) -> dict[str, object]:
    try:
        payload = graph_queries.build_stakeholder_view(
            stakeholder_id=stakeholder_id,
            from_date=from_date,
            to_date=to_date,
            include_graph=include_graph,
        )
    except GraphUnavailable:
        return JSONResponse(status_code=503, content={"error": "neo4j_unavailable"})

    if payload is None:
        raise HTTPException(status_code=404, detail="stakeholder_not_found")
    return payload
