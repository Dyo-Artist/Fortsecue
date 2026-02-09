from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any, Callable, Deque, Dict, List, Mapping, MutableMapping, Sequence

from logos.graphio.upsert import SCHEMA_STORE, upsert_agent_assist
from logos.graphio.neo4j_client import GraphUnavailable, get_client
from logos.memory import get_agent_context_rules
from logos.model_tiers import ModelConfigError, ModelSelection, get_model_for
from logos.normalise.bundle import build_agent_bundle

logger = logging.getLogger(__name__)


class AgentContextBuffer:
    """Ephemeral buffer to retain recent agent dialogue turns."""

    def __init__(
        self,
        max_entries: int | None = None,
        *,
        memory_rules: Mapping[str, Any] | None = None,
    ) -> None:
        context_rules = get_agent_context_rules(memory_rules)
        configured_limit = context_rules.get("context_turn_limit")
        self.max_entries = max_entries if max_entries is not None else int(configured_limit or 50)
        self._turns: Deque[Dict[str, object]] = deque(maxlen=self.max_entries)

    def add_turn(
        self,
        user_id: str,
        query: str,
        response: str,
        *,
        timestamp: datetime | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> None:
        """Append a dialogue turn, keeping only the most recent entries."""

        entry: MutableMapping[str, object] = {
            "timestamp": timestamp or datetime.now(timezone.utc),
            "user_id": user_id,
            "query": query,
            "response": response,
        }
        if metadata:
            entry["metadata"] = dict(metadata)
        self._turns.append(entry)

    def recent(self, *, limit: int | None = None, user_id: str | None = None) -> List[Dict[str, object]]:
        """Return the most recent dialogue turns, optionally filtered by user."""

        turns: Sequence[Dict[str, object]] = list(self._turns)
        if user_id is not None:
            turns = [turn for turn in turns if turn.get("user_id") == user_id]
        if limit is not None:
            return list(turns[-limit:])
        return list(turns)


def _select_model(task: str, resolver: Callable[[str], ModelSelection]) -> ModelSelection:
    """Resolve the model selection for a task with graceful fallback."""

    try:
        return resolver(task)
    except ModelConfigError:
        logger.info("Falling back to rule_only tier for task '%s' due to config error", task)
        return ModelSelection(task=task, tier="rule_only", name="rule_engine", parameters={})


def _rule_summary(text: str, *, max_words: int) -> str:
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
    schema_store: object | None = None,
) -> None:
    """Upsert the agent and link it to the requesting user with ASSISTS."""

    timestamp = now or datetime.now(timezone.utc)
    client = client_factory()
    store = schema_store or SCHEMA_STORE

    agent, user, assists_rel = build_agent_bundle(
        user_id,
        person_name=user_name,
        agent_id=agent_id,
        agent_name=agent_name,
        created_by=actor_id,
        source_uri=source_uri,
    )
    if agent_role:
        agent.properties.setdefault("role", agent_role)

    def _tx(tx):
        upsert_agent_assist(tx, agent, user, assists_rel, timestamp, schema_store=store, user=actor_id)

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
    context_buffer: AgentContextBuffer | None = None,
    memory_rules: Mapping[str, Any] | None = None,
) -> dict:
    """Generate a summary and ensure the assisting agent is recorded."""

    selection = _select_model("summary_interaction", model_selector)
    context_rules = get_agent_context_rules(memory_rules)
    summary = _rule_summary(text, max_words=int(context_rules.get("fallback_summary_max_words", 40)))

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

    if context_buffer:
        context_buffer.add_turn(
            user_id,
            text,
            summary,
            metadata={"agent_id": agent_id, "task": "summary_interaction", "model": selection.name},
        )

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
    context_buffer: AgentContextBuffer | None = None,
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

    if context_buffer:
        context_buffer.add_turn(
            user_id,
            risk_context,
            explanation,
            metadata={"agent_id": agent_id, "task": "reasoning_risk_explanation", "model": selection.name},
        )

    return {
        "explanation": explanation,
        "model": selection.name,
        "tier": selection.tier,
        "agent_id": agent_id,
    }
__all__ = [
    "AgentContextBuffer",
    "record_agent_assist",
    "summarise_interaction_for_user",
    "explain_risk_for_user",
]
