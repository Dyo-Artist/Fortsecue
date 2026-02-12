from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from math import exp
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from logos.graphio.neo4j_client import GraphUnavailable
from logos.knowledgebase.store import KnowledgebaseStore

POLICY_ID = "reasoning_path_scoring"
POLICY_VERSION = "1.0.0"
POLICY_KB_PATH = "models/reasoning_path_policy.yml"
REINFORCEMENT_LOG_REL_PATH = "data/reinforcement_log.jsonl"
OUTCOMES = ("acknowledged", "materialised", "false_positive")
FEATURE_KEYS = (
    "path_length",
    "recency",
    "sentiment_slope",
    "commitment_age",
    "influence_centrality",
)


@dataclass(slots=True)
class ReasoningPathPolicy:
    id: str
    version: str
    trained_at: str
    outcomes: tuple[str, ...]
    coefficients: dict[str, dict[str, float]]
    intercepts: dict[str, float]


def _normalise_outcome(value: Any) -> str:
    return str(value or "").strip().lower()


def _version_tuple(version: str) -> tuple[int, int, int]:
    try:
        major, minor, patch = [int(part) for part in str(version).split(".")]
        return major, minor, patch
    except (TypeError, ValueError):
        return (1, 0, 0)


def _next_version(version: str) -> str:
    major, minor, patch = _version_tuple(version)
    return f"{major}.{minor}.{patch + 1}"


def _timestamp_to_iso(value: Any) -> str:
    parsed = _normalise_timestamp(value)
    if parsed is None:
        return datetime.now(timezone.utc).isoformat()
    return parsed.isoformat()


def _retraining_config(store: KnowledgebaseStore) -> dict[str, Any]:
    payload = store.read_yaml_file(POLICY_KB_PATH)
    policy_block = payload.get("reasoning_policy") if isinstance(payload, Mapping) else {}
    retraining = policy_block.get("retraining") if isinstance(policy_block, Mapping) else {}
    if not isinstance(retraining, Mapping):
        return {}
    return dict(retraining)


def _reinforcement_log_path(store: KnowledgebaseStore, retraining_cfg: Mapping[str, Any]) -> Path:
    configured = retraining_cfg.get("reinforcement_log")
    rel_path = str(configured) if isinstance(configured, str) and configured.strip() else REINFORCEMENT_LOG_REL_PATH
    return store.base_path.parent / rel_path


def _existing_reinforcement_keys(path: Path) -> set[str]:
    keys: set[str] = set()
    if not path.exists():
        return keys
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue
            key = payload.get("sample_key")
            if isinstance(key, str):
                keys.add(key)
    return keys


def _build_sample_key(row: Mapping[str, Any]) -> str:
    alert_id = str(row.get("alert_id") or "")
    outcome = _normalise_outcome(row.get("outcome_label") or row.get("outcome"))
    timestamp = _timestamp_to_iso(row.get("timestamp"))
    if alert_id:
        return f"{alert_id}|{outcome}|{timestamp}"
    features = row.get("path_features") if isinstance(row.get("path_features"), Mapping) else row.get("features")
    feature_keys = sorted(str(item) for item in features.keys()) if isinstance(features, Mapping) else []
    return f"anon|{outcome}|{timestamp}|{','.join(feature_keys)}"


def sync_reinforcement_log(
    rows: Sequence[Mapping[str, Any]],
    *,
    kb_store: KnowledgebaseStore,
    retraining_cfg: Mapping[str, Any],
) -> int:
    path = _reinforcement_log_path(kb_store, retraining_cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _existing_reinforcement_keys(path)
    appended = 0

    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            features = row.get("path_features") if isinstance(row.get("path_features"), Mapping) else row.get("features")
            if not isinstance(features, Mapping):
                continue
            outcome = _normalise_outcome(row.get("outcome_label") or row.get("outcome"))
            if outcome not in OUTCOMES:
                continue
            sample_key = _build_sample_key(row)
            if sample_key in existing:
                continue

            payload = {
                "sample_key": sample_key,
                "alert_id": row.get("alert_id"),
                "path_features": {str(key): _feature_value(features, str(key)) for key in features.keys()},
                "model_score": _feature_value(row, "model_score"),
                "outcome_label": outcome,
                "timestamp": _timestamp_to_iso(row.get("timestamp")),
            }
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
            existing.add(sample_key)
            appended += 1

    return appended



def _sigmoid(value: float) -> float:
    if value >= 0:
        z = exp(-value)
        return 1.0 / (1.0 + z)
    z = exp(value)
    return z / (1.0 + z)


def _normalise_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        token = value.strip()
        if not token:
            return None
        if token.endswith("Z"):
            token = token[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(token)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _feature_value(features: Mapping[str, Any], key: str) -> float:
    raw = features.get(key, 0.0)
    if isinstance(raw, (int, float)):
        return float(raw)
    return 0.0


def _edge_type_features(edges: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    counts: dict[str, float] = {}
    for edge in edges:
        rel_type = str(edge.get("rel") or "").strip()
        if not rel_type:
            continue
        feature_key = f"edge_type::{rel_type.lower()}"
        counts[feature_key] = counts.get(feature_key, 0.0) + 1.0
    total = sum(counts.values())
    if total <= 0:
        return {}
    return {feature: value / total for feature, value in counts.items()}


def extract_path_features(
    *,
    nodes: Sequence[Mapping[str, Any]],
    edges: Sequence[Mapping[str, Any]],
    now: datetime | None = None,
) -> dict[str, float]:
    current = now or datetime.now(timezone.utc)
    path_length = float(len(edges))

    recency_values: list[float] = []
    for edge in edges:
        props = edge.get("props") if isinstance(edge.get("props"), Mapping) else {}
        seen = None
        for key in ("at", "interaction_at", "occurred_at", "created_at", "updated_at", "timestamp"):
            if key in props:
                seen = _normalise_timestamp(props.get(key))
                if seen is not None:
                    break
        if seen is None:
            continue
        age_days = max((current - seen).total_seconds() / 86400.0, 0.0)
        recency_values.append(1.0 / (1.0 + age_days))
    recency = sum(recency_values) / len(recency_values) if recency_values else 0.5

    sentiment_series: list[float] = []
    for node in nodes:
        sentiment = node.get("sentiment_score", node.get("sentiment"))
        if isinstance(sentiment, (int, float)):
            sentiment_series.append(float(sentiment))
    sentiment_slope = 0.0
    if len(sentiment_series) >= 2:
        sentiment_slope = (sentiment_series[-1] - sentiment_series[0]) / max(len(sentiment_series) - 1, 1)

    commitment_ages: list[float] = []
    for node in nodes:
        due_date = _normalise_timestamp(node.get("due_date"))
        if due_date is None:
            continue
        commitment_ages.append(max((current - due_date).total_seconds() / 86400.0, 0.0))
    commitment_age = max(commitment_ages) if commitment_ages else 0.0

    influence_values: list[float] = []
    for node in nodes:
        value = node.get("influence_centrality", node.get("influence_score"))
        if isinstance(value, (int, float)):
            influence_values.append(float(value))
    influence_centrality = max(influence_values) if influence_values else 0.0

    features = {
        "path_length": path_length,
        "recency": recency,
        "sentiment_slope": sentiment_slope,
        "commitment_age": commitment_age,
        "influence_centrality": influence_centrality,
    }
    features.update(_edge_type_features(edges))
    return features


def _fit_binary_logistic(
    samples: Sequence[Mapping[str, float]],
    labels: Sequence[int],
    *,
    epochs: int = 300,
    learning_rate: float = 0.08,
    l2: float = 0.001,
) -> tuple[dict[str, float], float]:
    keys = sorted({key for sample in samples for key in sample.keys()})
    weights = {key: 0.0 for key in keys}
    bias = 0.0
    n = max(len(samples), 1)

    for _ in range(epochs):
        grad_w = {key: 0.0 for key in keys}
        grad_b = 0.0
        for sample, target in zip(samples, labels):
            linear = bias + sum(sample.get(key, 0.0) * weights[key] for key in keys)
            pred = _sigmoid(linear)
            error = pred - float(target)
            grad_b += error
            for key in keys:
                grad_w[key] += error * sample.get(key, 0.0)

        for key in keys:
            grad = (grad_w[key] / n) + l2 * weights[key]
            weights[key] -= learning_rate * grad
        bias -= learning_rate * (grad_b / n)

    return weights, bias


def train_reasoning_policy(
    labelled_rows: Sequence[Mapping[str, Any]],
    *,
    policy_id: str = POLICY_ID,
    version: str = POLICY_VERSION,
    trained_at: str | None = None,
) -> ReasoningPathPolicy:
    samples: list[dict[str, float]] = []
    labels: list[str] = []
    for row in labelled_rows:
        outcome = _normalise_outcome(row.get("outcome_label") or row.get("outcome"))
        if outcome not in OUTCOMES:
            continue
        features = row.get("path_features") if isinstance(row.get("path_features"), Mapping) else None
        if features is None:
            features = row.get("features") if isinstance(row.get("features"), Mapping) else None
        if features is None:
            nodes = row.get("nodes") if isinstance(row.get("nodes"), Sequence) else []
            edges = row.get("edges") if isinstance(row.get("edges"), Sequence) else []
            features = extract_path_features(nodes=nodes, edges=edges)
        normalised = {str(key): _feature_value(features, str(key)) for key in features.keys()}
        samples.append(normalised)
        labels.append(outcome)

    if not samples:
        trained = trained_at or datetime.now(timezone.utc).isoformat()
        return ReasoningPathPolicy(
            id=policy_id,
            version=version,
            trained_at=trained,
            outcomes=OUTCOMES,
            coefficients={outcome: {key: 0.0 for key in FEATURE_KEYS} for outcome in OUTCOMES},
            intercepts={outcome: 0.0 for outcome in OUTCOMES},
        )

    coefficients: dict[str, dict[str, float]] = {}
    intercepts: dict[str, float] = {}
    for outcome in OUTCOMES:
        binary = [1 if label == outcome else 0 for label in labels]
        weights, bias = _fit_binary_logistic(samples, binary)
        coefficients[outcome] = weights
        intercepts[outcome] = bias

    return ReasoningPathPolicy(
        id=policy_id,
        version=version,
        trained_at=trained_at or datetime.now(timezone.utc).isoformat(),
        outcomes=OUTCOMES,
        coefficients=coefficients,
        intercepts=intercepts,
    )


def _policy_payload(policy: ReasoningPathPolicy) -> dict[str, Any]:
    return {
        "reasoning_policy": {
            "id": policy.id,
            "version": policy.version,
            "trained_at": policy.trained_at,
            "outcomes": list(policy.outcomes),
            "intercepts": policy.intercepts,
            "coefficients": policy.coefficients,
        }
    }


def persist_reasoning_policy(
    policy: ReasoningPathPolicy,
    *,
    kb_store: KnowledgebaseStore | None = None,
    graph_run: Callable[[str, Mapping[str, Any]], Sequence[Mapping[str, Any]]] | None = None,
    archive_entry: Mapping[str, Any] | None = None,
) -> None:
    store = kb_store or KnowledgebaseStore()
    current_payload = store.read_yaml_file(POLICY_KB_PATH)
    next_payload = _policy_payload(policy)
    current_policy = current_payload.get("reasoning_policy") if isinstance(current_payload, Mapping) else {}
    if isinstance(current_policy, Mapping):
        for key in ("retraining", "coefficient_archive"):
            if key in current_policy and key not in next_payload["reasoning_policy"]:
                next_payload["reasoning_policy"][key] = current_policy.get(key)
    if archive_entry:
        archive = next_payload["reasoning_policy"].get("coefficient_archive")
        history = list(archive) if isinstance(archive, list) else []
        history.append(dict(archive_entry))
        max_archive = 25
        retraining = next_payload["reasoning_policy"].get("retraining")
        if isinstance(retraining, Mapping):
            cfg_max = retraining.get("max_archive_entries")
            if isinstance(cfg_max, int) and cfg_max > 0:
                max_archive = cfg_max
        next_payload["reasoning_policy"]["coefficient_archive"] = history[-max_archive:]

    store.update_yaml_file(POLICY_KB_PATH, next_payload, reason="Updated reasoning path scoring policy")

    if graph_run is None:
        return
    coefficients_payload = {
        "intercepts": policy.intercepts,
        "weights": policy.coefficients,
        "outcomes": list(policy.outcomes),
    }
    graph_run(
        (
            "MERGE (p:ReasoningPolicy {id: $id}) "
            "SET p.version = $version, "
            "    p.coefficients = $coefficients_json, "
            "    p.trained_at = datetime($trained_at)"
        ),
        {
            "id": policy.id,
            "version": policy.version,
            "coefficients_json": coefficients_payload,
            "trained_at": policy.trained_at,
        },
    )


def load_reasoning_policy(*, kb_store: KnowledgebaseStore | None = None) -> ReasoningPathPolicy:
    store = kb_store or KnowledgebaseStore()
    payload = store.read_yaml_file(POLICY_KB_PATH)
    policy_data = payload.get("reasoning_policy") if isinstance(payload, Mapping) else None
    if not isinstance(policy_data, Mapping):
        return train_reasoning_policy([])
    coefficients = policy_data.get("coefficients") if isinstance(policy_data.get("coefficients"), Mapping) else {}
    intercepts = policy_data.get("intercepts") if isinstance(policy_data.get("intercepts"), Mapping) else {}
    outcomes = tuple(str(item) for item in policy_data.get("outcomes", OUTCOMES))
    return ReasoningPathPolicy(
        id=str(policy_data.get("id") or POLICY_ID),
        version=str(policy_data.get("version") or POLICY_VERSION),
        trained_at=str(policy_data.get("trained_at") or datetime.now(timezone.utc).isoformat()),
        outcomes=outcomes,
        coefficients={
            str(key): {str(feature): float(value) for feature, value in values.items() if isinstance(value, (int, float))}
            for key, values in coefficients.items()
            if isinstance(values, Mapping)
        },
        intercepts={str(key): float(value) for key, value in intercepts.items() if isinstance(value, (int, float))},
    )


def evaluate_policy(
    policy: ReasoningPathPolicy,
    features: Mapping[str, float],
) -> tuple[float, str, dict[str, float]]:
    materialised_weights = policy.coefficients.get("materialised", {})
    intercept = float(policy.intercepts.get("materialised", 0.0))
    logit = intercept
    contributions: dict[str, float] = {}
    for feature_key, feature_value in features.items():
        if not isinstance(feature_value, (int, float)):
            continue
        weight = float(materialised_weights.get(feature_key, 0.0))
        contribution = float(feature_value) * weight
        contributions[feature_key] = contribution
        logit += contribution

    score = _sigmoid(logit)
    top_features = sorted(contributions.items(), key=lambda item: abs(item[1]), reverse=True)[:3]
    top_text = ", ".join(f"{key}={value:+.3f}" for key, value in top_features) if top_features else "none"
    explanation = f"Path score {score:.2f} from logistic policy v{policy.version}; top contributions: {top_text}."
    return score, explanation, contributions


def evaluate_dataset(policy: ReasoningPathPolicy, labelled_rows: Sequence[Mapping[str, Any]]) -> float:
    if not labelled_rows:
        return 0.0
    correct = 0
    total = 0
    for row in labelled_rows:
        outcome = str(row.get("outcome") or "")
        features = row.get("features") if isinstance(row.get("features"), Mapping) else {}
        score, _, _ = evaluate_policy(policy, features)
        predicted = "materialised" if score >= 0.55 else "acknowledged" if score >= 0.35 else "false_positive"
        correct += 1 if predicted == outcome else 0
        total += 1
    return correct / total if total else 0.0


def load_or_train_and_persist_policy(
    *,
    run_query: Callable[[str, Mapping[str, Any]], Sequence[Mapping[str, Any]]],
    kb_store: KnowledgebaseStore | None = None,
) -> ReasoningPathPolicy:
    store = kb_store or KnowledgebaseStore()
    retraining_cfg = _retraining_config(store)
    loaded = load_reasoning_policy(kb_store=store)

    try:
        rows = run_query(
            (
                "MATCH (a) "
                "WHERE any(label IN labels(a) WHERE toLower(label) CONTAINS 'alert') "
                "AND a.outcome IN $outcomes "
                "AND a.path_features IS NOT NULL "
                "RETURN a.id AS alert_id, "
                "       a.path_features AS path_features, "
                "       coalesce(a.model_score, a.risk_score, 0.0) AS model_score, "
                "       a.outcome AS outcome_label, "
                "       coalesce(a.outcome_at, a.updated_at, a.created_at) AS timestamp "
                "LIMIT 1000"
            ),
            {"outcomes": list(OUTCOMES)},
        )
    except GraphUnavailable:
        rows = []

    labelled = [row for row in rows if isinstance(row, Mapping)]
    new_samples = sync_reinforcement_log(labelled, kb_store=store, retraining_cfg=retraining_cfg)

    threshold = retraining_cfg.get("incremental_threshold", 25)
    if not isinstance(threshold, int) or threshold <= 0:
        threshold = 25

    if loaded.coefficients.get("materialised") and new_samples < threshold:
        return loaded

    if not labelled:
        return loaded

    next_version = _next_version(loaded.version)
    trained = train_reasoning_policy(labelled, version=next_version)
    archive_entry = {
        "version": loaded.version,
        "trained_at": loaded.trained_at,
        "archived_at": datetime.now(timezone.utc).isoformat(),
        "intercepts": loaded.intercepts,
        "coefficients": loaded.coefficients,
    }
    persist_reasoning_policy(trained, kb_store=store, graph_run=run_query, archive_entry=archive_entry)
    return trained
