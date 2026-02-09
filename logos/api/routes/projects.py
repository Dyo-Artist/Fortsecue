"""Project map endpoints for LOGOS."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from ...graphio import queries as graph_queries
from ...graphio.neo4j_client import GraphUnavailable

router = APIRouter()


@router.get("/projects/{project_id}/map")
async def project_map_view(
    project_id: str, include_graph: bool = Query(True)
) -> dict[str, object]:
    try:
        payload = graph_queries.build_project_map_view(
            project_id=project_id, include_graph=include_graph
        )
    except GraphUnavailable:
        return JSONResponse(status_code=503, content={"error": "neo4j_unavailable"})

    if payload is None:
        raise HTTPException(status_code=404, detail="project_not_found")
    return payload
