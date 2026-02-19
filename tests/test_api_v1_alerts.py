import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from logos import main
from logos.api.routes import alerts as alerts_route
from logos.graphio import queries as graph_queries


def test_api_v1_alerts_filters(monkeypatch):
    client = TestClient(main.app)
    captured: dict[str, object] = {}

    pipeline_calls: list[str] = []

    def fake_run_pipeline(name, payload, context):  # type: ignore[unused-argument]
        pipeline_calls.append(name)
        return payload

    monkeypatch.setattr(alerts_route, "run_pipeline", fake_run_pipeline)

    def fake_list_alerts(
        *,
        types=None,
        statuses=None,
        project_id=None,
        stakeholder_id=None,
        org_id=None,
        page=1,
        page_size=20,
    ):
        captured.update(
            {
                "types": types,
                "statuses": statuses,
                "project_id": project_id,
                "stakeholder_id": stakeholder_id,
                "org_id": org_id,
                "page": page,
                "page_size": page_size,
            }
        )
        return (
            [
                {
                    "id": "a1",
                    "type": "unresolved_commitment",
                    "status": "open",
                }
            ],
            12,
        )

    monkeypatch.setattr(graph_queries, "list_alerts", fake_list_alerts)

    response = client.get(
        "/api/v1/alerts"
        "?type=unresolved_commitment"
        "&status=open"
        "&project_id=pr1"
        "&stakeholder_id=st1"
        "&org_id=o1"
        "&page=2"
        "&page_size=5"
    )

    assert response.status_code == 200
    assert captured == {
        "types": ["unresolved_commitment"],
        "statuses": ["open"],
        "project_id": "pr1",
        "stakeholder_id": "st1",
        "org_id": "o1",
        "page": 2,
        "page_size": 5,
    }
    assert pipeline_calls == ["pipeline.reasoning_alerts"]
    assert response.json() == {
        "items": [
            {
                "id": "a1",
                "type": "unresolved_commitment",
                "status": "open",
            }
        ],
        "page": 2,
        "page_size": 5,
        "total_items": 12,
        "total_pages": 3,
    }



def test_api_v1_alert_outcome_logs_reinforcement(monkeypatch):
    client = TestClient(main.app)

    class FakeClient:
        def run(self, query, params):
            assert params["status"] == "closed"
            return [{"alert_id": "a1", "path_features": {"path_length": 2.0}, "model_score": 0.88}]

    monkeypatch.setattr(alerts_route, "get_client", lambda: FakeClient())

    captured = {}

    def fake_record_alert_outcome(**kwargs):
        captured.update(kwargs)
        return True, "logged_and_retrained"

    monkeypatch.setattr(alerts_route, "record_alert_outcome", fake_record_alert_outcome)

    response = client.patch("/api/v1/alerts/a1/outcome", json={"status": "closed"})

    assert response.status_code == 200
    assert response.json()["retraining_action"] == "logged_and_retrained"
    assert captured["alert_id"] == "a1"
    assert captured["outcome_status"] == "closed"
    assert captured["features"]["path_length"] == 2.0
