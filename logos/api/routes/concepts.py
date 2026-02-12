"""Concept governance endpoints for LOGOS."""

from __future__ import annotations

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse

from logos.graphio.neo4j_client import GraphUnavailable
from logos.learning.clustering.concept_governance import ConceptPromotionError, promote_concept

router = APIRouter()
legacy_router = APIRouter()


def _promote(concept_id: str, promoted_by: str):
    try:
        result = promote_concept(concept_id, promoted_by=promoted_by)
    except ConceptPromotionError as exc:
        status_code = 404 if exc.code == "CONCEPT_NOT_FOUND" else 409
        return JSONResponse(
            status_code=status_code,
            content={
                "error": exc.code.lower(),
                "message": exc.message,
                "concept_id": exc.concept_id,
            },
        )
    except GraphUnavailable:
        return JSONResponse(status_code=503, content={"error": "neo4j_unavailable"})

    return {
        "concept_id": result.concept_id,
        "status": result.status,
        "converted_relationships": result.converted_relationships,
        "promotion_provenance": dict(result.provenance),
    }


@router.post("/concept/promote/{concept_id}")
async def promote_concept_endpoint(
    concept_id: str,
    x_actor_id: str | None = Header(default=None),
):
    return _promote(concept_id=concept_id, promoted_by=x_actor_id or "api")


@legacy_router.post("/concept/promote/{concept_id}")
async def promote_concept_endpoint_legacy(
    concept_id: str,
    x_actor_id: str | None = Header(default=None),
):
    return _promote(concept_id=concept_id, promoted_by=x_actor_id or "api")
