from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from logos.knowledgebase.store import KnowledgebaseStore
from logos.reasoning.path_policy import evaluate_policy, load_reasoning_policy

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ReasoningPathModel:
    version: str
    trained: bool
    coefficients: dict[str, float]
    intercept: float


@dataclass(slots=True)
class PathScoreResult:
    path_id: str
    path_nodes: list[dict[str, Any]]
    path_edges: list[dict[str, Any]]
    feature_vector: dict[str, float]
    risk_score: float
    influence_score: float
    feature_contributions: dict[str, float]
    explanation: str
    model_version: str
    model_trained: bool


def _is_model_trained(intercept: float, coefficients: Mapping[str, float], trained_at: str) -> bool:
    if abs(intercept) > 1e-9:
        return True
    if any(abs(float(value)) > 1e-9 for value in coefficients.values()):
        return True
    return trained_at != "1970-01-01T00:00:00+00:00"


def load_reasoning_path_model(*, kb_store: KnowledgebaseStore | None = None) -> ReasoningPathModel:
    policy = load_reasoning_policy(kb_store=kb_store)
    materialised = policy.coefficients.get("materialised", {})
    coefficients = {
        str(key): float(value)
        for key, value in materialised.items()
        if isinstance(value, (int, float))
    }
    intercept = float(policy.intercepts.get("materialised", 0.0))
    return ReasoningPathModel(
        version=policy.version,
        trained=_is_model_trained(intercept, coefficients, policy.trained_at),
        coefficients=coefficients,
        intercept=intercept,
    )


def _safe_float(value: Any, default: float = 0.0) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return default


def score_entity_path(
    *,
    model: ReasoningPathModel,
    features: Mapping[str, float],
    interactions: Sequence[Mapping[str, Any]],
    commitments: Sequence[Mapping[str, Any]],
    path_id: str,
    path_nodes: Sequence[Mapping[str, Any]],
    path_edges: Sequence[Mapping[str, Any]],
) -> PathScoreResult:
    if not model.trained:
        logger.warning("Reasoning path model is not trained; using explicit neutral fallback")
        influence_score = min(1.0, _safe_float(features.get("interaction_count"), 0.0) / 10.0)
        return PathScoreResult(
            path_id=path_id,
            path_nodes=[dict(node) for node in path_nodes],
            path_edges=[dict(edge) for edge in path_edges],
            feature_vector={str(key): _safe_float(value) for key, value in features.items()},
            risk_score=0.5,
            influence_score=influence_score,
            feature_contributions={},
            explanation="Neutral fallback because reasoning path model is not trained.",
            model_version=model.version,
            model_trained=False,
        )

    policy_like = type("PolicyLike", (), {"coefficients": {"materialised": model.coefficients}, "intercepts": {"materialised": model.intercept}, "version": model.version})
    score, explanation, contributions = evaluate_policy(policy_like, features)
    influence_signal = _safe_float(features.get("interaction_count"), 0.0)
    influence_score = min(1.0, influence_signal / 10.0)
    return PathScoreResult(
        path_id=path_id,
        path_nodes=[dict(node) for node in path_nodes],
        path_edges=[dict(edge) for edge in path_edges],
        feature_vector={str(key): _safe_float(value) for key, value in features.items()},
        risk_score=float(score),
        influence_score=influence_score,
        feature_contributions={str(k): float(v) for k, v in contributions.items()},
        explanation=explanation,
        model_version=model.version,
        model_trained=True,
    )
