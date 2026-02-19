from __future__ import annotations

import logging
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence
from uuid import NAMESPACE_URL, uuid5

import yaml

from logos.core.pipeline_executor import PipelineContext, STAGE_REGISTRY
from logos.graphio.neo4j_client import GraphUnavailable, get_client
from logos.graphio.schema_store import SchemaStore
from logos.knowledgebase.store import KnowledgebaseStore
from logos.learning.reasoning.path_model import load_reasoning_path_model, score_entity_path
from logos.reasoning.path_policy import extract_path_features

logger = logging.getLogger(__name__)


def _trace(context: Dict[str, Any], stage_name: str) -> None:
    trace: list[str] = context.setdefault("trace", [])  # type: ignore[assignment]
    trace.append(stage_name)


def _labels_by_keywords(labels: Iterable[str], keywords: Iterable[str]) -> list[str]:
    lowered = [(label, label.lower()) for label in labels]
    return [
        label
        for label, lowered_label in lowered
        if any(keyword in lowered_label for keyword in keywords)
    ]


def _properties_by_keywords(
    schema_store: SchemaStore, labels: Sequence[str], keywords: Iterable[str]
) -> list[str]:
    matches: set[str] = set()
    for label in labels:
        definition = schema_store.node_types.get(label)
        if not definition:
            continue
        for prop in definition.properties:
            lowered = prop.lower()
            if any(keyword in lowered for keyword in keywords):
                matches.add(prop)
    return sorted(matches)


def _coalesce_expr(alias: str, properties: Sequence[str]) -> str:
    if not properties:
        return "NULL"
    joined = ", ".join(f"{alias}.{prop}" for prop in properties)
    return f"coalesce({joined})"


def _extract_param(rule: Mapping[str, Any] | None, name: str, default: Any) -> Any:
    if not isinstance(rule, Mapping):
        return default
    params = rule.get("params") if isinstance(rule.get("params"), Mapping) else {}
    if not isinstance(params, Mapping):
        return default
    value = params.get(name, default)
    if isinstance(value, Mapping):
        return value.get("initial", default)
    return value


def _rule_enabled(rule: Mapping[str, Any] | None) -> bool:
    if not isinstance(rule, Mapping):
        return False
    return bool(rule.get("enabled", True))


def _load_rules_file(base_path: Path, rel_path: str) -> dict[str, Any]:
    path = base_path / rel_path
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}
    except yaml.YAMLError as exc:  # pragma: no cover - defensive guard
        logger.warning("Failed to parse rules file %s: %s", path, exc)
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _load_alert_rules(context: Mapping[str, Any]) -> dict[str, Any]:
    kb_path = context.get("knowledgebase_path")
    kb_store = KnowledgebaseStore(base_path=kb_path) if kb_path else KnowledgebaseStore()
    return _load_rules_file(kb_store.base_path, "rules/alerts.yml")


def _normalise_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if hasattr(value, "to_native"):
        try:
            value = value.to_native()
        except Exception:
            pass
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _sentiment_value(interaction: Mapping[str, Any]) -> float | None:
    raw_score = interaction.get("sentiment_score", interaction.get("sentiment"))
    if isinstance(raw_score, (int, float)):
        return float(raw_score)
    label = interaction.get("sentiment_label", interaction.get("sentiment"))
    if isinstance(label, str):
        lowered = label.lower()
        if "negative" in lowered:
            return -1.0
        if "positive" in lowered:
            return 1.0
        if "neutral" in lowered:
            return 0.0
    return None


def _extract_identity_candidates(entity: Mapping[str, Any]) -> list[dict[str, Any]]:
    candidates = entity.get("identity_candidates")
    if not isinstance(candidates, list):
        return []
    enriched: list[dict[str, Any]] = []
    for candidate in candidates:
        if isinstance(candidate, Mapping):
            candidate_id = candidate.get("id") or candidate.get("entity_id")
            if candidate_id:
                enriched.append(
                    {
                        "id": str(candidate_id),
                        "confidence": float(candidate.get("confidence", 0.0) or 0.0),
                        "context": candidate.get("context"),
                    }
                )
    return enriched




def _build_path_payload(entry: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, float]]:
    interactions = entry.get("interactions") if isinstance(entry.get("interactions"), list) else []
    commitments = entry.get("commitments") if isinstance(entry.get("commitments"), list) else []

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    for interaction in interactions:
        if not isinstance(interaction, Mapping):
            continue
        node: dict[str, Any] = {}
        sentiment = _sentiment_value(interaction)
        if sentiment is not None:
            node["sentiment_score"] = sentiment
        influence = interaction.get("influence_centrality", interaction.get("influence_score"))
        if isinstance(influence, (int, float)):
            node["influence_centrality"] = float(influence)
        if node:
            nodes.append(node)

        timestamp = _normalise_datetime(interaction.get("interaction_time") or interaction.get("at") or interaction.get("created_at"))
        edge_props = {"timestamp": timestamp.isoformat() if timestamp else datetime.now(timezone.utc).isoformat()}
        edges.append({"rel": "INTERACTION", "props": edge_props})

    for commitment in commitments:
        if not isinstance(commitment, Mapping):
            continue
        node: dict[str, Any] = {}
        due = _normalise_datetime(commitment.get("due_date"))
        if due is not None:
            node["due_date"] = due.isoformat()
        if node:
            nodes.append(node)

        edge_props = {"timestamp": due.isoformat() if due else datetime.now(timezone.utc).isoformat()}
        edges.append({"rel": "COMMITMENT", "props": edge_props})

    return nodes, edges, extract_path_features(nodes=nodes, edges=edges)

def _pick_primary_id(entity: Mapping[str, Any]) -> tuple[str | None, list[dict[str, Any]]]:
    primary = entity.get("id")
    candidates = _extract_identity_candidates(entity)
    if primary:
        return str(primary), candidates
    if candidates:
        sorted_candidates = sorted(candidates, key=lambda item: item.get("confidence", 0.0), reverse=True)
        return str(sorted_candidates[0].get("id")), candidates
    return None, candidates


def _relationship_type(schema_store: SchemaStore, keywords: Sequence[str], fallback: str) -> str:
    rel_types = list(schema_store.relationship_types.keys())
    matches = _labels_by_keywords(rel_types, keywords)
    if matches:
        return matches[0]
    return fallback


def _alert_label(schema_store: SchemaStore) -> str:
    labels = list(schema_store.node_types.keys())
    matches = _labels_by_keywords(labels, ["alert"])
    return matches[0] if matches else "Alert"


def _entity_label_sets(schema_store: SchemaStore) -> dict[str, list[str]]:
    labels = list(schema_store.node_types.keys())
    return {
        "stakeholder": _labels_by_keywords(labels, ["person", "org", "stakeholder", "agent"]),
        "project": _labels_by_keywords(labels, ["project"]),
        "interaction": _labels_by_keywords(labels, ["interaction"]),
        "commitment": _labels_by_keywords(labels, ["commitment"]),
    }


def _alert_id(rule_id: str, entity_id: str, subject_id: str | None = None) -> str:
    key = f"{rule_id}:{entity_id}"
    if subject_id:
        key = f"{key}:{subject_id}"
    return str(uuid5(NAMESPACE_URL, key))


@STAGE_REGISTRY.register("R1_COLLECT_TARGETS")
def collect_targets(bundle: Any, ctx: PipelineContext) -> Dict[str, Any]:
    context = ctx.to_mapping()
    _trace(context, "R1_COLLECT_TARGETS")

    schema_store = context.get("schema_store")
    if not isinstance(schema_store, SchemaStore):
        schema_store = SchemaStore()

    rules_payload = _load_alert_rules(context)
    alert_rules = rules_payload.get("alerts") if isinstance(rules_payload.get("alerts"), Mapping) else {}

    sentiment_rule = alert_rules.get("sentiment_drop") if isinstance(alert_rules, Mapping) else {}
    window_days = int(_extract_param(sentiment_rule, "window_days", 14))
    interaction_limit = int(context.get("interaction_limit", 200))
    commitment_limit = int(context.get("commitment_limit", 200))

    label_sets = _entity_label_sets(schema_store)
    interaction_labels = label_sets.get("interaction", [])
    commitment_labels = label_sets.get("commitment", [])

    interaction_time_props = _properties_by_keywords(schema_store, interaction_labels, ["at", "date", "time"])
    commitment_due_props = _properties_by_keywords(schema_store, commitment_labels, ["due", "date"])

    interaction_time_expr = _coalesce_expr("i", interaction_time_props)
    commitment_due_expr = _coalesce_expr("c", commitment_due_props)

    client_factory = context.get("graph_client_factory") or get_client

    collected = {
        "interactions": [],
        "commitments": [],
        "window_days": window_days,
    }

    try:
        if interaction_labels:
            interaction_query = (
                "MATCH (i) "
                "WHERE any(label IN labels(i) WHERE label IN $interaction_labels) "
                f"WITH i, {interaction_time_expr} AS interaction_time "
                "WHERE interaction_time IS NULL OR interaction_time >= datetime() - duration({days: $window_days}) "
                "OPTIONAL MATCH (i)--(n) "
                "RETURN i{.*, labels: labels(i), interaction_time: interaction_time} AS interaction, "
                "collect(DISTINCT n{.*, labels: labels(n)}) AS related "
                "ORDER BY interaction_time DESC "
                "LIMIT $limit"
            )
            interactions = client_factory().run(
                interaction_query,
                {
                    "interaction_labels": interaction_labels,
                    "window_days": window_days,
                    "limit": interaction_limit,
                },
            )
            collected["interactions"] = interactions

        if commitment_labels:
            commitment_query = (
                "MATCH (c) "
                "WHERE any(label IN labels(c) WHERE label IN $commitment_labels) "
                f"WITH c, {commitment_due_expr} AS due_date "
                "OPTIONAL MATCH (c)--(n) "
                "RETURN c{.*, labels: labels(c), due_date: due_date} AS commitment, "
                "collect(DISTINCT n{.*, labels: labels(n)}) AS related "
                "LIMIT $limit"
            )
            commitments = client_factory().run(
                commitment_query,
                {"commitment_labels": commitment_labels, "limit": commitment_limit},
            )
            collected["commitments"] = commitments
    except GraphUnavailable:
        logger.warning("Graph unavailable during R1_COLLECT_TARGETS")
        collected["graph_unavailable"] = True

    payload: Dict[str, Any] = {}
    if isinstance(bundle, Mapping):
        payload.update(bundle)
    payload.update(
        {
            "pipeline": "reasoning_alerts",
            "rules": alert_rules,
            "targets": collected,
            "scores": {},
            "alerts": [],
        }
    )
    return payload


@STAGE_REGISTRY.register("R2_COMPUTE_SCORES")
def compute_scores(bundle: Mapping[str, Any], ctx: PipelineContext) -> Dict[str, Any]:
    context = ctx.to_mapping()
    _trace(context, "R2_COMPUTE_SCORES")

    if not isinstance(bundle, Mapping):
        raise TypeError("R2_COMPUTE_SCORES expects a mapping bundle")

    schema_store = context.get("schema_store")
    if not isinstance(schema_store, SchemaStore):
        schema_store = SchemaStore()

    label_sets = _entity_label_sets(schema_store)
    stakeholder_labels = set(label_sets.get("stakeholder", []))
    project_labels = set(label_sets.get("project", []))

    targets = bundle.get("targets") if isinstance(bundle.get("targets"), Mapping) else {}
    interactions = targets.get("interactions") if isinstance(targets.get("interactions"), list) else []
    commitments = targets.get("commitments") if isinstance(targets.get("commitments"), list) else []

    rules = bundle.get("rules") if isinstance(bundle.get("rules"), Mapping) else {}
    unresolved_rule = rules.get("unresolved_commitment") if isinstance(rules, Mapping) else {}
    status_excluded = _extract_param(unresolved_rule, "status_excluded", ["done", "cancelled"]) or []
    status_excluded = [str(item).lower() for item in status_excluded if item]

    kb_path = context.get("knowledgebase_path")
    kb_store = KnowledgebaseStore(base_path=kb_path) if kb_path else KnowledgebaseStore()
    path_model = load_reasoning_path_model(kb_store=kb_store)

    entity_scores: dict[str, dict[str, Any]] = {}

    def _ensure_entity(entity: Mapping[str, Any], category: str) -> tuple[str | None, dict[str, Any]]:
        primary_id, candidates = _pick_primary_id(entity)
        if not primary_id:
            return None, {}
        entry = entity_scores.setdefault(
            primary_id,
            {
                "entity_id": primary_id,
                "labels": entity.get("labels", []),
                "category": category,
                "identity_candidates": candidates,
                "interactions": [],
                "commitments": [],
                "scores": {},
            },
        )
        return primary_id, entry

    for row in interactions:
        interaction = row.get("interaction") if isinstance(row, Mapping) else None
        related = row.get("related") if isinstance(row, Mapping) else None
        if not isinstance(interaction, Mapping) or not isinstance(related, list):
            continue
        for entity in related:
            if not isinstance(entity, Mapping):
                continue
            labels = set(entity.get("labels") or [])
            category = "stakeholder" if labels & stakeholder_labels else "project" if labels & project_labels else None
            if not category:
                continue
            entity_id, entry = _ensure_entity(entity, category)
            if not entity_id:
                continue
            entry["interactions"].append(interaction)

    for row in commitments:
        commitment = row.get("commitment") if isinstance(row, Mapping) else None
        related = row.get("related") if isinstance(row, Mapping) else None
        if not isinstance(commitment, Mapping) or not isinstance(related, list):
            continue
        for entity in related:
            if not isinstance(entity, Mapping):
                continue
            labels = set(entity.get("labels") or [])
            category = "stakeholder" if labels & stakeholder_labels else "project" if labels & project_labels else None
            if not category:
                continue
            entity_id, entry = _ensure_entity(entity, category)
            if not entity_id:
                continue
            entry["commitments"].append(commitment)

    for entry in entity_scores.values():
        interactions_sorted = sorted(
            entry.get("interactions", []),
            key=lambda item: _normalise_datetime(item.get("interaction_time")) or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        negative_streak = 0
        streak = 0
        for interaction in interactions_sorted:
            sentiment = _sentiment_value(interaction)
            if sentiment is None:
                continue
            if sentiment < 0:
                streak += 1
                negative_streak = max(negative_streak, streak)
            else:
                streak = 0

        interaction_count = len(interactions_sorted)

        overdue_commitments = 0
        for commitment in entry.get("commitments", []):
            status = commitment.get("status")
            status_str = str(status).lower() if status is not None else ""
            if status_str and status_str in status_excluded:
                continue
            due = _normalise_datetime(commitment.get("due_date"))
            if due and due < datetime.now(timezone.utc):
                overdue_commitments += 1

        model_feature_vector = {
            "negative_sentiment_streak": float(negative_streak),
            "interaction_count": float(interaction_count),
            "overdue_commitments": float(overdue_commitments),
        }
        path_nodes, path_edges, policy_feature_vector = _build_path_payload(entry)
        path_id = f"{entry.get('entity_id')}:reasoning-path"
        logger.info(
            "execution_trace.path_scoring_invocation entity_id=%s interactions=%d commitments=%d features=%s",
            entry.get("entity_id"),
            len(entry.get("interactions", [])),
            len(entry.get("commitments", [])),
            sorted(model_feature_vector.keys()),
        )
        path_score = score_entity_path(
            model=path_model,
            features=model_feature_vector,
            interactions=entry.get("interactions", []),
            commitments=entry.get("commitments", []),
            path_id=path_id,
            path_nodes=path_nodes,
            path_edges=path_edges,
        )

        top_contributions = sorted(
            path_score.feature_contributions.items(),
            key=lambda item: abs(item[1]),
            reverse=True,
        )[:3]
        entry["scores"] = {
            "risk_score": float(path_score.risk_score),
            "influence_score": float(path_score.influence_score),
            "negative_sentiment_streak": int(negative_streak),
            "interaction_count": interaction_count,
            "overdue_commitments": overdue_commitments,
            "feature_contributions": path_score.feature_contributions,
            "explanation": path_score.explanation,
            "model_version": path_score.model_version,
            "model_trained": path_score.model_trained,
            "model_score": float(path_score.risk_score),
            "path_features": {**policy_feature_vector, **path_score.feature_vector},
            "scored_path": {
                "path_id": path_score.path_id,
                "path_nodes": path_score.path_nodes,
                "path_edges": path_score.path_edges,
                "feature_vector": {**policy_feature_vector, **path_score.feature_vector},
                "score": float(path_score.risk_score),
                "model_version": path_score.model_version,
                "explanation": {
                    "summary": path_score.explanation,
                    "top_contributing_features": [
                        {"feature": key, "contribution": float(value)} for key, value in top_contributions
                    ],
                },
            },
        }

    payload = dict(bundle)
    payload["scores"] = entity_scores
    return payload


@STAGE_REGISTRY.register("R3_APPLY_RULES_AND_MODELS")
def apply_rules(bundle: Mapping[str, Any], ctx: PipelineContext) -> Dict[str, Any]:
    context = ctx.to_mapping()
    _trace(context, "R3_APPLY_RULES_AND_MODELS")

    if not isinstance(bundle, Mapping):
        raise TypeError("R3_APPLY_RULES_AND_MODELS expects a mapping bundle")

    rules = bundle.get("rules") if isinstance(bundle.get("rules"), Mapping) else {}
    alerts_rules = rules if isinstance(rules, Mapping) else {}

    unresolved_rule = alerts_rules.get("unresolved_commitment") if isinstance(alerts_rules, Mapping) else {}
    sentiment_rule = alerts_rules.get("sentiment_drop") if isinstance(alerts_rules, Mapping) else {}

    unresolved_enabled = _rule_enabled(unresolved_rule)
    sentiment_enabled = _rule_enabled(sentiment_rule)

    min_model_score = float(_extract_param(sentiment_rule, "min_model_score", 0.6))
    targets = bundle.get("targets") if isinstance(bundle.get("targets"), Mapping) else {}
    alerts: list[dict[str, Any]] = []

    scores = bundle.get("scores") if isinstance(bundle.get("scores"), Mapping) else {}
    now = datetime.now(timezone.utc)

    for entity_id, entry in scores.items():
        if not isinstance(entry, Mapping):
            continue
        score_block = entry.get("scores") if isinstance(entry.get("scores"), Mapping) else {}
        scored_path = score_block.get("scored_path") if isinstance(score_block.get("scored_path"), Mapping) else {}
        model_score = float(score_block.get("model_score", score_block.get("risk_score", 0.0)) or 0.0)

        if not score_block.get("model_trained"):
            logger.warning("Alert scoring fallback active for entity_id=%s because path model is not trained", entity_id)

        if model_score < min_model_score:
            continue

        if unresolved_enabled:
            alerts.append(
                {
                    "id": _alert_id("learned_unresolved_commitment", entity_id),
                    "type": "unresolved_commitment",
                    "status": "open",
                    "entity_id": entity_id,
                    "entity_candidates": entry.get("identity_candidates", []),
                    "rule_id": "learned_path_score",
                    "summary": f"Model scored path risk at {model_score:.2f}",
                    "risk_score": score_block.get("risk_score"),
                    "influence_score": score_block.get("influence_score"),
                    "scored_path": scored_path,
                    "path_features": scored_path.get("feature_vector") if isinstance(scored_path, Mapping) else None,
                    "model_score": model_score,
                    "model_version": score_block.get("model_version"),
                    "provenance": {
                        "pipeline": "pipeline.reasoning_alerts",
                        "rule": "learned_path_score",
                        "evaluated_at": now.isoformat(),
                    },
                }
            )

        if sentiment_enabled:
            alerts.append(
                {
                    "id": _alert_id("learned_sentiment_drop", entity_id),
                    "type": "sentiment_drop",
                    "status": "open",
                    "entity_id": entity_id,
                    "entity_candidates": entry.get("identity_candidates", []),
                    "rule_id": "learned_path_score",
                    "summary": f"Model scored path risk at {model_score:.2f}",
                    "risk_score": score_block.get("risk_score"),
                    "influence_score": score_block.get("influence_score"),
                    "scored_path": scored_path,
                    "path_features": scored_path.get("feature_vector") if isinstance(scored_path, Mapping) else None,
                    "model_score": model_score,
                    "model_version": score_block.get("model_version"),
                    "provenance": {
                        "pipeline": "pipeline.reasoning_alerts",
                        "rule": "learned_path_score",
                        "evaluated_at": now.isoformat(),
                    },
                }
            )

    payload = dict(bundle)
    payload["alerts"] = alerts
    return payload


@STAGE_REGISTRY.register("R4_MATERIALISE_ALERTS")
def materialise_alerts(bundle: Mapping[str, Any], ctx: PipelineContext) -> Dict[str, Any]:
    context = ctx.to_mapping()
    _trace(context, "R4_MATERIALISE_ALERTS")

    if not isinstance(bundle, Mapping):
        raise TypeError("R4_MATERIALISE_ALERTS expects a mapping bundle")

    schema_store = context.get("schema_store")
    if not isinstance(schema_store, SchemaStore):
        schema_store = SchemaStore()

    alerts = bundle.get("alerts") if isinstance(bundle.get("alerts"), list) else []
    if not alerts:
        payload = dict(bundle)
        payload["materialised"] = 0
        return payload

    alert_label = _alert_label(schema_store)
    rel_type = _relationship_type(schema_store, ["relate", "associate", "affect"], "RELATES_TO")

    client_factory = context.get("graph_client_factory") or get_client
    now = datetime.now(timezone.utc)
    materialised = 0

    try:
        for alert in alerts:
            if not isinstance(alert, Mapping):
                continue
            alert_id = alert.get("id")
            entity_id = alert.get("entity_id")
            if not alert_id:
                continue

            props = {
                "id": str(alert_id),
                "type": alert.get("type"),
                "status": alert.get("status", "open"),
                "summary": alert.get("summary"),
                "rule_id": alert.get("rule_id"),
                "provenance": alert.get("provenance"),
                "risk_score": alert.get("risk_score"),
                "influence_score": alert.get("influence_score"),
                "negative_streak": alert.get("negative_streak"),
                "window_days": alert.get("window_days"),
                "commitment_id": alert.get("commitment_id"),
                "due_date": alert.get("due_date"),
                "age_days": alert.get("age_days"),
                "entity_candidates": alert.get("entity_candidates"),
                "path_features": alert.get("path_features"),
                "scored_path": alert.get("scored_path"),
                "model_score": alert.get("model_score", alert.get("risk_score")),
                "model_version": alert.get("model_version"),
                "updated_at": now.isoformat(),
            }
            if "created_at" not in props:
                props["created_at"] = now.isoformat()

            entity_ids = []
            if entity_id:
                entity_ids.append(str(entity_id))
            commitment_id = alert.get("commitment_id")
            if commitment_id:
                entity_ids.append(str(commitment_id))

            cypher = (
                f"MERGE (a:{alert_label} {{id: $id}}) "
                "SET a += $props "
                "WITH a "
                "UNWIND $entity_ids AS entity_id "
                "MATCH (e {id: entity_id}) "
                f"MERGE (a)-[r:{rel_type}]->(e) "
                "RETURN a.id AS id"
            )
            client_factory().run(
                cypher,
                {"id": props["id"], "props": props, "entity_ids": entity_ids},
            )
            schema_store.record_node_type(alert_label, set(props.keys()), concept_kind="AlertType")
            schema_store.record_relationship_type(rel_type, set())
            materialised += 1
    except GraphUnavailable:
        logger.warning("Graph unavailable during R4_MATERIALISE_ALERTS")
        payload = dict(bundle)
        payload["materialised"] = 0
        payload["graph_unavailable"] = True
        return payload

    payload = dict(bundle)
    payload["materialised"] = materialised
    return payload


__all__ = [
    "collect_targets",
    "compute_scores",
    "apply_rules",
    "materialise_alerts",
]
