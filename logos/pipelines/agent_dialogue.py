from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping
from uuid import uuid4

from logos.core.pipeline_executor import PipelineContext, STAGE_REGISTRY
from logos.graphio.neo4j_client import GraphUnavailable
from logos.graphio.queries import get_top_paths
from logos.graphio.search import search_entities
from logos.llm.prompt import PromptEngine, PromptEngineError
from logos.models.bundles import FeedbackBundle, InteractionMeta

logger = logging.getLogger(__name__)
PROMPT_ENGINE = PromptEngine()

_INTENT_PROMPT_MAP = {
    "summary": "agent/summary.yml",
    "risk": "agent/explain_risk.yml",
    "who": "agent/suggest_next_actions.yml",
    "search": "agent/suggest_next_actions.yml",
}


def _trace(context: Dict[str, Any], stage_name: str) -> None:
    trace: list[str] = context.setdefault("trace", [])  # type: ignore[assignment]
    trace.append(stage_name)


def _extract_query(bundle: Any) -> str:
    if isinstance(bundle, Mapping):
        for key in ("query", "q", "text", "raw_text"):
            value = bundle.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    value = getattr(bundle, "query", None) or getattr(bundle, "text", None)
    if isinstance(value, str):
        return value.strip()
    return ""


def _extract_keywords(text: str) -> list[str]:
    tokens = re.findall(r"\b[\w-]+\b", text.lower())
    return sorted({token for token in tokens if len(token) > 2})


def _extract_ids(bundle: Any) -> dict[str, str | None]:
    if isinstance(bundle, Mapping):
        return {
            "project_id": bundle.get("project_id"),
            "stakeholder_id": bundle.get("stakeholder_id"),
        }
    return {
        "project_id": getattr(bundle, "project_id", None),
        "stakeholder_id": getattr(bundle, "stakeholder_id", None),
    }


def _intent_from_keywords(keywords: Iterable[str]) -> str:
    keyword_set = set(keywords)
    if "risk" in keyword_set or "risks" in keyword_set:
        return "risk"
    if "summary" in keyword_set or "summarise" in keyword_set or "summarize" in keyword_set:
        return "summary"
    if "who" in keyword_set or "owner" in keyword_set:
        return "who"
    return "search"


def _build_plan(query: str, keywords: list[str], ids: Mapping[str, str | None]) -> dict[str, Any]:
    intent = _intent_from_keywords(keywords)
    actions: list[dict[str, Any]] = []
    if intent == "risk":
        actions.append(
            {
                "type": "top_paths",
                "params": {
                    "project_id": ids.get("project_id"),
                    "stakeholder_id": ids.get("stakeholder_id"),
                    "limit": 3,
                },
            }
        )
    else:
        actions.append({"type": "search_entities", "params": {"query": query}})
    return {"intent": intent, "query": query, "keywords": keywords, "actions": actions}


def _safe_feedback_meta(bundle: Any, ctx: PipelineContext) -> InteractionMeta:
    if isinstance(bundle, Mapping):
        meta = bundle.get("meta")
        if isinstance(meta, Mapping) and meta.get("interaction_id"):
            return InteractionMeta(
                interaction_id=str(meta.get("interaction_id")),
                interaction_type=str(meta.get("interaction_type") or "agent_dialogue"),
            )
    meta_attr = getattr(bundle, "meta", None)
    if meta_attr and getattr(meta_attr, "interaction_id", None):
        return InteractionMeta(
            interaction_id=str(meta_attr.interaction_id),
            interaction_type=str(getattr(meta_attr, "interaction_type", "agent_dialogue") or "agent_dialogue"),
        )
    fallback_id = ctx.request_id or uuid4().hex
    return InteractionMeta(interaction_id=fallback_id, interaction_type="agent_dialogue")


def _concept_assignments(reasoning_paths: Iterable[Mapping[str, Any]]) -> list[dict[str, str]]:
    assignments: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for path in reasoning_paths:
        nodes = path.get("nodes") if isinstance(path.get("nodes"), Iterable) else []
        for node in nodes:
            if not isinstance(node, Mapping):
                continue
            node_id = str(node.get("id") or "").strip()
            concept_id = str(node.get("concept_id") or node.get("concept") or "").strip()
            concept_kind = str(node.get("concept_kind") or node.get("kind") or "").strip()
            if not node_id or not concept_id:
                continue
            signature = (node_id, concept_id, concept_kind)
            if signature in seen:
                continue
            seen.add(signature)
            assignments.append(
                {
                    "node_id": node_id,
                    "concept_id": concept_id,
                    "concept_kind": concept_kind,
                }
            )
    return assignments


def _learned_weight_signals(reasoning_paths: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    for index, path in enumerate(reasoning_paths, start=1):
        contributions = path.get("contributions") if isinstance(path.get("contributions"), Mapping) else {}
        top_contributions = sorted(
            (
                (str(name), float(value))
                for name, value in contributions.items()
                if isinstance(value, (int, float))
            ),
            key=lambda item: abs(item[1]),
            reverse=True,
        )[:3]
        signals.append(
            {
                "path_rank": index,
                "score": float(path.get("score") or 0.0),
                "policy_explanation": str(path.get("explanation") or ""),
                "top_weighted_features": [
                    {"feature": feature, "weighted_value": weighted_value}
                    for feature, weighted_value in top_contributions
                ],
            }
        )
    return signals


@STAGE_REGISTRY.register("A1_PARSE_QUERY")
def stage_parse_query(bundle: Any, ctx: PipelineContext) -> Dict[str, Any]:
    context = ctx.to_mapping()
    _trace(context, "A1_PARSE_QUERY")

    query = _extract_query(bundle)
    keywords = _extract_keywords(query)
    ids = _extract_ids(bundle)

    return {
        "query": query,
        "keywords": keywords,
        "project_id": ids.get("project_id"),
        "stakeholder_id": ids.get("stakeholder_id"),
    }


@STAGE_REGISTRY.register("A2_PLAN_DIALECTIC")
def stage_plan_dialectic(bundle: Any, ctx: PipelineContext) -> Dict[str, Any]:
    context = ctx.to_mapping()
    _trace(context, "A2_PLAN_DIALECTIC")

    query = bundle.get("query", "") if isinstance(bundle, Mapping) else _extract_query(bundle)
    keywords = bundle.get("keywords", []) if isinstance(bundle, Mapping) else _extract_keywords(query)
    ids = _extract_ids(bundle)

    plan = _build_plan(query, list(keywords), ids)
    return {**(dict(bundle) if isinstance(bundle, Mapping) else {}), "plan": plan}


@STAGE_REGISTRY.register("A3_QUERY_GRAPH")
def stage_query_graph(bundle: Any, ctx: PipelineContext) -> Dict[str, Any]:
    context = ctx.to_mapping()
    _trace(context, "A3_QUERY_GRAPH")

    plan = bundle.get("plan", {}) if isinstance(bundle, Mapping) else {}
    actions = plan.get("actions", []) if isinstance(plan, Mapping) else []
    results: list[dict[str, Any]] = []
    reasoning_paths: list[dict[str, Any]] = []

    for action in actions:
        if not isinstance(action, Mapping):
            continue
        action_type = action.get("type")
        params = action.get("params") if isinstance(action.get("params"), Mapping) else {}
        try:
            if action_type == "search_entities":
                query = params.get("query") or plan.get("query") or ""
                results = search_entities(str(query))
            elif action_type == "top_paths":
                reasoning_paths = get_top_paths(
                    project_id=params.get("project_id"),
                    stakeholder_id=params.get("stakeholder_id"),
                    limit=int(params.get("limit", 3)),
                )
        except GraphUnavailable:
            logger.warning("agent_dialogue_graph_unavailable", extra={"action": action_type})
        except ValueError as exc:
            logger.warning("agent_dialogue_query_failed", extra={"action": action_type, "error": str(exc)})

    return {
        **(dict(bundle) if isinstance(bundle, Mapping) else {}),
        "results": results,
        "reasoning_paths": reasoning_paths,
    }


@STAGE_REGISTRY.register("A4_COMPOSE_RESPONSE")
def stage_compose_response(bundle: Any, ctx: PipelineContext) -> Dict[str, Any]:
    context = ctx.to_mapping()
    _trace(context, "A4_COMPOSE_RESPONSE")

    plan = bundle.get("plan", {}) if isinstance(bundle, Mapping) else {}
    intent = plan.get("intent", "search") if isinstance(plan, Mapping) else "search"
    query = plan.get("query", "") if isinstance(plan, Mapping) else ""
    results = bundle.get("results", []) if isinstance(bundle, Mapping) else []
    reasoning_paths = bundle.get("reasoning_paths", []) if isinstance(bundle, Mapping) else []

    target = plan.get("actions", [{}])[0].get("params", {}) if isinstance(plan, Mapping) else {}
    prompt_path = _INTENT_PROMPT_MAP.get(str(intent), "agent/suggest_next_actions.yml")
    prompt_context = {
        "query": query,
        "intent": intent,
        "project_id": target.get("project_id") if isinstance(target, Mapping) else "",
        "stakeholder_id": target.get("stakeholder_id") if isinstance(target, Mapping) else "",
        "results_json": results,
        "reasoning_paths_json": reasoning_paths,
    }

    concept_assignments = _concept_assignments(reasoning_paths)
    learned_weight_signals = _learned_weight_signals(reasoning_paths)
    prompt_context["concept_assignments_json"] = concept_assignments
    prompt_context["learned_weight_signals_json"] = learned_weight_signals

    try:
        agent_response = PROMPT_ENGINE.run_prompt(prompt_path, prompt_context)
    except PromptEngineError as exc:
        message = f"Prompt execution failed: {exc}"
        logger.warning("agent_dialogue_prompt_failed", extra={"error": message, "prompt": prompt_path})
        raise PromptEngineError(message) from exc

    return {
        **(dict(bundle) if isinstance(bundle, Mapping) else {}),
        "agent_response": agent_response,
        "reasoning": reasoning_paths,
        "concept_assignments": concept_assignments,
        "learned_weight_signals": learned_weight_signals,
        "rendered_prompt_path": prompt_path,
    }


@STAGE_REGISTRY.register("A5_CAPTURE_FEEDBACK")
def stage_capture_feedback(bundle: Any, ctx: PipelineContext) -> Dict[str, Any]:
    context = ctx.to_mapping()
    _trace(context, "A5_CAPTURE_FEEDBACK")

    plan = bundle.get("plan", {}) if isinstance(bundle, Mapping) else {}
    intent = plan.get("intent", "search") if isinstance(plan, Mapping) else "search"
    meta = _safe_feedback_meta(bundle, ctx)

    feedback = FeedbackBundle(
        meta=meta,
        feedback="agent_dialogue",
        timestamp=datetime.now(timezone.utc),
        user_id=ctx.user_id,
    )
    feedback.intent = intent
    feedback.query = plan.get("query")
    feedback.response = bundle.get("agent_response")

    return {
        "agent_response": bundle.get("agent_response"),
        "reasoning": bundle.get("reasoning", []),
        "concept_assignments": bundle.get("concept_assignments", []),
        "learned_weight_signals": bundle.get("learned_weight_signals", []),
        "feedback_bundle": feedback.model_dump(),
    }


__all__ = [
    "stage_parse_query",
    "stage_plan_dialectic",
    "stage_query_graph",
    "stage_compose_response",
    "stage_capture_feedback",
]
