import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from logos import main
from logos.api.routes import agents as agents_routes


def test_agent_query_endpoint(monkeypatch):
    client = TestClient(main.app)
    captured = {}

    def fake_run_pipeline(name, input_bundle, ctx):
        captured["name"] = name
        captured["input_bundle"] = input_bundle
        captured["ctx_user_id"] = ctx.user_id
        captured["ctx_person_id"] = ctx.context_data.get("person_id")
        return {
            "agent_response": "Agent says hi.",
            "reasoning": [{"path": "p1"}],
            "proposed_actions": [{"type": "notify"}],
            "links": [{"href": "/projects/pr_456"}],
            "feedback_bundle": {
                "meta": {"interaction_id": "ix-1", "interaction_type": "agent_dialogue"}
            },
        }

    def fake_append_feedback(bundle):
        captured["feedback_bundle"] = bundle

    monkeypatch.setattr(agents_routes, "run_pipeline", fake_run_pipeline)
    monkeypatch.setattr(agents_routes, "append_feedback", fake_append_feedback)

    response = client.post(
        "/api/v1/agent/query",
        json={
            "query": "What risks affect Project X?",
            "person_id": "p_123",
            "context": {"project_id": "pr_456"},
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "agent_response": "Agent says hi.",
        "reasoning": [{"path": "p1"}],
        "proposed_actions": [{"type": "notify"}],
        "links": [{"href": "/projects/pr_456"}],
    }
    assert captured["name"] == "pipeline.agent_dialogue"
    assert captured["input_bundle"] == {
        "query": "What risks affect Project X?",
        "stakeholder_id": "p_123",
        "project_id": "pr_456",
        "context": {"project_id": "pr_456"},
    }
    assert captured["ctx_user_id"] == "p_123"
    assert captured["ctx_person_id"] == "p_123"
    assert captured["feedback_bundle"].query == "What risks affect Project X?"
    assert captured["feedback_bundle"].response == "Agent says hi."
