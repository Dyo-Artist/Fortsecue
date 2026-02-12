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


def test_compute_scores_explanation_contains_feature_contributions_and_path_breakdown(monkeypatch):
    def fake_load_reasoning_path_model(*, kb_store=None):
        class Model:
            version = "test-v1"
            trained = True
            coefficients = {"interaction_count": 0.2, "overdue_commitments": 0.4, "negative_sentiment_streak": 0.3}
            intercept = 0.1

        return Model()

    monkeypatch.setattr(
        "logos.pipelines.reasoning_alerts.load_reasoning_path_model",
        fake_load_reasoning_path_model,
    )

    scored = compute_scores(_bundle(), PipelineContext())
    entry = scored["scores"]["person-1"]["scores"]

    assert entry["model_trained"] is True
    assert isinstance(entry["feature_contributions"], dict)
    assert entry["feature_contributions"]
    assert isinstance(entry["path_breakdown"], list)
    assert {item["path_segment"] for item in entry["path_breakdown"]} == {"interactions", "commitments"}
    assert entry["path_features"]["interaction_count"] == 1.0
    assert entry["model_score"] == entry["risk_score"]
