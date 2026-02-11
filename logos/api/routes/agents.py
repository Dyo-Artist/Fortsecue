"""Agent dialogue routes for LOGOS."""
from __future__ import annotations

import logging
from typing import Any, Mapping
from uuid import uuid4

from fastapi import APIRouter
from pydantic import BaseModel, Field

from logos.core.pipeline_executor import PipelineContext, run_pipeline
from logos.feedback.store import append_feedback
from logos.models.bundles import FeedbackBundle, InteractionMeta

logger = logging.getLogger(__name__)

router = APIRouter()


class AgentQueryRequest(BaseModel):
    query: str = Field(..., min_length=1)
    person_id: str | None = None
    context: dict[str, Any] | None = None


def _build_feedback_bundle(
    *,
    feedback_payload: Mapping[str, Any] | None,
    request_id: str,
    person_id: str | None,
    query: str,
    agent_response: str | None,
    context: Mapping[str, Any] | None,
) -> FeedbackBundle:
    if feedback_payload:
        bundle = FeedbackBundle.model_validate(feedback_payload)
    else:
        bundle = FeedbackBundle(
            meta=InteractionMeta(
                interaction_id=request_id,
                interaction_type="agent_dialogue",
                created_by=person_id,
            )
        )
    bundle.query = query
    bundle.response = agent_response
    if context:
        bundle.context = dict(context)
    if person_id:
        bundle.person_id = person_id
    return bundle


def _persist_feedback(bundle: FeedbackBundle) -> None:
    try:
        append_feedback(bundle)
    except Exception:  # pragma: no cover - avoid failing API responses
        logger.exception("agent_feedback_persist_failed", extra={"interaction_id": bundle.meta.interaction_id})


@router.post("/agent/query")
async def query_agent(payload: AgentQueryRequest) -> dict[str, Any]:
    request_id = uuid4().hex
    context = payload.context or {}
    input_bundle = {
        "query": payload.query,
        "stakeholder_id": payload.person_id,
        "project_id": context.get("project_id"),
        "context": context,
    }
    ctx = PipelineContext(
        request_id=request_id,
        user_id=payload.person_id or "api",
        context_data={"person_id": payload.person_id, "context": context},
    )

    result = run_pipeline("pipeline.agent_dialogue", input_bundle, ctx)
    agent_response = result.get("agent_response") if isinstance(result, Mapping) else None
    reasoning = result.get("reasoning", []) if isinstance(result, Mapping) else []
    feedback_bundle = _build_feedback_bundle(
        feedback_payload=result.get("feedback_bundle") if isinstance(result, Mapping) else None,
        request_id=request_id,
        person_id=payload.person_id,
        query=payload.query,
        agent_response=agent_response,
        context=context,
    )
    _persist_feedback(feedback_bundle)

    response: dict[str, Any] = {
        "agent_response": agent_response,
        "reasoning": reasoning,
    }
    if isinstance(result, Mapping):
        proposed_actions = result.get("proposed_actions")
        links = result.get("links")
        if proposed_actions is not None:
            response["proposed_actions"] = proposed_actions
        if links is not None:
            response["links"] = links
    return response
