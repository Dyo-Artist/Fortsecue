from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable

from logos.graphio import upsert
from logos.graphio.neo4j_client import GraphUnavailable, get_client
from logos.model_tiers import ModelConfigError, ModelSelection, get_model_for

logger = logging.getLogger(__name__)


def _select_model(task: str, resolver: Callable[[str], ModelSelection]) -> ModelSelection:
    """Resolve the model selection for a task with graceful fallback."""

    try:
        return resolver(task)
    except ModelConfigError:
        logger.info("Falling back to rule_only tier for task '%s' due to config error", task)
        return ModelSelection(task=task, tier="rule_only", name="rule_engine", parameters={})


def _rule_summary(text: str, *, max_words: int = 40) -> str:
    """Lightweight rule-based summary when LLM/ML tiers are unavailable."""

    tokens = text.split()
    if len(tokens) <= max_words:
        return text.strip()
    return " ".join(tokens[:max_words])


def _rule_risk_explanation(risk_text: str) -> str:
    """Rule-based risk explanation stub that echoes the identified risk."""

    trimmed = risk_text.strip()
    if not trimmed:
        return "No risk context provided."
    return f"Key risk factors identified: {trimmed}"


def record_agent_assist(
    user_id: str,
    user_name: str | None = None,
    *,
    agent_id: str = "agent_logos",
    agent_name: str = "LOGOS Assistant",
    agent_role: str | None = "assistant",
    source_uri: str | None = "agent://logos",
    actor_id: str | None = "logos_system",
    client_factory: Callable[[], object] = get_client,
    now: datetime | None = None,
) -> None:
    """Upsert the agent and link it to the requesting user with ASSISTS."""

    timestamp = now or datetime.now(timezone.utc)
    client = client_factory()

    agent = upsert.AgentModel(
        id=agent_id,
        name=agent_name,
        role=agent_role,
        source_uri=source_uri,
        created_by=actor_id,
        updated_by=actor_id,
    )
    user = upsert.PersonModel(id=user_id, name=user_name or user_id, source_uri=source_uri)

    def _tx(tx):
        upsert.upsert_agent_assist(tx, agent, user, timestamp)

    client.run_in_tx(_tx)


def summarise_interaction_for_user(
    text: str,
    user_id: str,
    *,
    user_name: str | None = None,
    agent_id: str = "agent_logos",
    agent_name: str = "LOGOS Assistant",
    model_selector: Callable[[str], ModelSelection] = get_model_for,
    record_assist_fn: Callable[..., None] = record_agent_assist,
) -> dict:
    """Generate a summary and ensure the assisting agent is recorded."""

    selection = _select_model("summary_interaction", model_selector)
    summary = _rule_summary(text)

    try:
        record_assist_fn(
            user_id,
            user_name,
            agent_id=agent_id,
            agent_name=agent_name,
            source_uri="agent://logos/summary",
        )
    except GraphUnavailable:
        logger.warning("Graph unavailable while recording agent assist for summary")

    return {"summary": summary, "model": selection.name, "tier": selection.tier, "agent_id": agent_id}


def explain_risk_for_user(
    risk_context: str,
    user_id: str,
    *,
    user_name: str | None = None,
    agent_id: str = "agent_logos",
    agent_name: str = "LOGOS Assistant",
    model_selector: Callable[[str], ModelSelection] = get_model_for,
    record_assist_fn: Callable[..., None] = record_agent_assist,
) -> dict:
    """Explain a risk with rule-only fallback and agent provenance."""

    selection = _select_model("reasoning_risk_explanation", model_selector)
    explanation = _rule_risk_explanation(risk_context)

    try:
        record_assist_fn(
            user_id,
            user_name,
            agent_id=agent_id,
            agent_name=agent_name,
            source_uri="agent://logos/risk_explanation",
        )
    except GraphUnavailable:
        logger.warning("Graph unavailable while recording agent assist for risk explanation")

    return {
        "explanation": explanation,
        "model": selection.name,
        "tier": selection.tier,
        "agent_id": agent_id,
    }
__all__ = [
    "record_agent_assist",
    "summarise_interaction_for_user",
    "explain_risk_for_user",
]
