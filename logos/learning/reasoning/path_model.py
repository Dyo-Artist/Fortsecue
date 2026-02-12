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
    risk_score: float
    influence_score: float
    feature_contributions: dict[str, float]
    path_breakdown: list[dict[str, Any]]
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
) -> PathScoreResult:
    path_breakdown = [
        {
            "path_segment": "interactions",
            "count": len(interactions),
            "sample_ids": [str(item.get("id")) for item in interactions[:3] if item.get("id")],
        },
        {
            "path_segment": "commitments",
            "count": len(commitments),
            "sample_ids": [str(item.get("id")) for item in commitments[:3] if item.get("id")],
        },
    ]

    if not model.trained:
        logger.warning("Reasoning path model is not trained; falling back to neutral scoring")
        influence_score = min(1.0, _safe_float(features.get("interaction_count"), 0.0) / 10.0)
        return PathScoreResult(
            risk_score=0.5,
            influence_score=influence_score,
            feature_contributions={},
            path_breakdown=path_breakdown,
            explanation="Neutral fallback because reasoning path model is not trained.",
            model_version=model.version,
            model_trained=False,
        )

    policy_like = type("PolicyLike", (), {"coefficients": {"materialised": model.coefficients}, "intercepts": {"materialised": model.intercept}, "version": model.version})
    score, explanation, contributions = evaluate_policy(policy_like, features)
    influence_signal = _safe_float(features.get("interaction_count"), 0.0)
    influence_score = min(1.0, influence_signal / 10.0)
    return PathScoreResult(
        risk_score=float(score),
        influence_score=influence_score,
        feature_contributions={str(k): float(v) for k, v in contributions.items()},
        path_breakdown=path_breakdown,
        explanation=explanation,
        model_version=model.version,
        model_trained=True,
    )
