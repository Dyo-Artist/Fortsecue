from __future__ import annotations

from datetime import datetime, timedelta, timezone

from logos.reasoning.path_policy import (
    evaluate_dataset,
    evaluate_policy,
    extract_path_features,
    train_reasoning_policy,
)


def _sample_features(path_length: float, recency: float, sentiment: float, commitment_age: float, influence: float):
    return {
        "path_length": path_length,
        "recency": recency,
        "sentiment_slope": sentiment,
        "commitment_age": commitment_age,
        "influence_centrality": influence,
    }


def test_train_reasoning_policy_on_synthetic_labelled_dataset():
    labelled = [
        {"outcome": "materialised", "features": _sample_features(3, 0.9, -0.5, 18, 0.9)},
        {"outcome": "materialised", "features": _sample_features(4, 0.8, -0.4, 14, 0.8)},
        {"outcome": "acknowledged", "features": _sample_features(2, 0.6, -0.1, 7, 0.6)},
        {"outcome": "acknowledged", "features": _sample_features(2, 0.5, 0.0, 6, 0.5)},
        {"outcome": "false_positive", "features": _sample_features(1, 0.2, 0.5, 1, 0.2)},
        {"outcome": "false_positive", "features": _sample_features(1, 0.1, 0.4, 0, 0.1)},
    ]

    policy = train_reasoning_policy(labelled)
    accuracy = evaluate_dataset(policy, labelled)

    assert accuracy >= 0.65

    score, explanation, contributions = evaluate_policy(
        policy,
        _sample_features(4, 0.85, -0.45, 16, 0.85),
    )
    assert score > 0.5
    assert "top contributions" in explanation
    assert "sentiment_slope" in contributions


def test_extract_path_features_includes_requested_dimensions():
    now = datetime(2026, 1, 20, tzinfo=timezone.utc)
    nodes = [
        {"id": "i-1", "sentiment_score": -0.6, "influence_centrality": 0.7},
        {"id": "i-2", "sentiment_score": -0.1, "due_date": (now - timedelta(days=12)).isoformat()},
    ]
    edges = [
        {"rel": "INFLUENCES", "props": {"at": (now - timedelta(days=3)).isoformat()}},
        {"rel": "RELATES_TO", "props": {"at": (now - timedelta(days=6)).isoformat()}},
    ]

    features = extract_path_features(nodes=nodes, edges=edges, now=now)

    assert set(features).issuperset(
        {
            "path_length",
            "recency",
            "sentiment_slope",
            "commitment_age",
            "influence_centrality",
            "edge_type::influences",
            "edge_type::relates_to",
        }
    )
    assert features["path_length"] == 2
    assert features["commitment_age"] >= 10
