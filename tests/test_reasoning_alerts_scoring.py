import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from logos.core.pipeline_executor import PipelineContext
from logos.pipelines.reasoning_alerts import compute_scores


def _bundle() -> dict:
    return {
        "targets": {
            "interactions": [
                {
                    "interaction": {
                        "id": "i1",
                        "interaction_time": "2026-01-01T00:00:00+00:00",
                        "sentiment": "negative",
                    },
                    "related": [{"id": "person-1", "labels": ["Person"]}],
                }
            ],
            "commitments": [
                {
                    "commitment": {
                        "id": "c1",
                        "status": "open",
                        "due_date": "2020-01-01T00:00:00+00:00",
                    },
                    "related": [{"id": "person-1", "labels": ["Person"]}],
                }
            ],
        },
        "rules": {
            "unresolved_commitment": {
                "params": {"status_excluded": ["done", "cancelled"]},
            }
        },
    }


def test_compute_scores_uses_neutral_fallback_when_path_model_untrained(caplog):
    ctx = PipelineContext()

    with caplog.at_level("WARNING"):
        scored = compute_scores(_bundle(), ctx)

    entry = scored["scores"]["person-1"]["scores"]
    assert entry["risk_score"] == 0.5
    assert entry["model_trained"] is False
    assert entry["feature_contributions"] == {}
    assert "not trained" in entry["explanation"].lower()
    assert any("not trained" in msg.lower() for msg in caplog.messages)


def test_compute_scores_invokes_path_model(monkeypatch):
    calls = {"count": 0}

    def fake_score_entity_path(*, model, features, interactions, commitments, path_id, path_nodes, path_edges):
        calls["count"] += 1

        from types import SimpleNamespace

        return SimpleNamespace(
            risk_score=0.77,
            influence_score=0.25,
            feature_contributions={"interaction_count": 0.33},
            explanation="ok",
            model_version="v-test",
            model_trained=True,
            path_id=path_id,
            path_nodes=list(path_nodes),
            path_edges=list(path_edges),
            feature_vector=dict(features),
        )

    monkeypatch.setattr("logos.pipelines.reasoning_alerts.score_entity_path", fake_score_entity_path)

    scored = compute_scores(_bundle(), PipelineContext())
    assert calls["count"] == 1
    entry = scored["scores"]["person-1"]["scores"]
    assert entry["model_score"] == 0.77


def test_compute_scores_includes_standard_scored_path_model():
    scored = compute_scores(_bundle(), PipelineContext())
    entry = scored["scores"]["person-1"]["scores"]
    scored_path = entry["scored_path"]

    assert set(scored_path.keys()) == {
        "path_id",
        "path_nodes",
        "path_edges",
        "feature_vector",
        "score",
        "model_version",
        "explanation",
    }
    assert "top_contributing_features" in scored_path["explanation"]
    assert entry["path_features"] == scored_path["feature_vector"]
