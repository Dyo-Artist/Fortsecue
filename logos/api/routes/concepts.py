"""Concept governance endpoints for LOGOS."""

from __future__ import annotations

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse

from logos.graphio.neo4j_client import GraphUnavailable
from logos.learning.clustering.concept_governance import (
    ConceptPromotionError,
    merge_proposed_concept,
    promote_concept,
    reject_proposed_concept,
)

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


def _merge(proposed_concept_id: str, target_concept_id: str, merged_by: str):
    try:
        result = merge_proposed_concept(proposed_concept_id, target_concept_id, merged_by=merged_by)
    except ConceptPromotionError as exc:
        status_code = 404 if exc.code in {"CONCEPT_NOT_FOUND", "TARGET_CONCEPT_NOT_FOUND"} else 409
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
        "proposed_concept_id": result.proposed_concept_id,
        "target_concept_id": result.target_concept_id,
        "status": result.status,
        "repointed_relationships": result.repointed_relationships,
        "merge_provenance": dict(result.provenance),
    }


def _reject(concept_id: str, rejected_by: str, reason: str | None = None):
    try:
        result = reject_proposed_concept(concept_id, rejected_by=rejected_by, reason=reason)
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
        "rejection_provenance": dict(result.provenance),
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


@router.post("/concept/merge/{proposed_concept_id}/{target_concept_id}")
async def merge_concept_endpoint(
    proposed_concept_id: str,
    target_concept_id: str,
    x_actor_id: str | None = Header(default=None),
):
    return _merge(
        proposed_concept_id=proposed_concept_id,
        target_concept_id=target_concept_id,
        merged_by=x_actor_id or "api",
    )


@legacy_router.post("/concept/merge/{proposed_concept_id}/{target_concept_id}")
async def merge_concept_endpoint_legacy(
    proposed_concept_id: str,
    target_concept_id: str,
    x_actor_id: str | None = Header(default=None),
):
    return _merge(
        proposed_concept_id=proposed_concept_id,
        target_concept_id=target_concept_id,
        merged_by=x_actor_id or "api",
    )


@router.post("/concept/reject/{concept_id}")
async def reject_concept_endpoint(
    concept_id: str,
    reason: str | None = None,
    x_actor_id: str | None = Header(default=None),
):
    return _reject(concept_id=concept_id, rejected_by=x_actor_id or "api", reason=reason)


@legacy_router.post("/concept/reject/{concept_id}")
async def reject_concept_endpoint_legacy(
    concept_id: str,
    reason: str | None = None,
    x_actor_id: str | None = Header(default=None),
):
    return _reject(concept_id=concept_id, rejected_by=x_actor_id or "api", reason=reason)
