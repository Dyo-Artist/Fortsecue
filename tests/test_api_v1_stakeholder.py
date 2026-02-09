import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from logos import main
from logos.graphio import queries


def test_api_v1_stakeholder_returns_payload(monkeypatch):
    client = TestClient(main.app)
    payload = {
        "stakeholder": {"entity_type": "person", "person": {"id": "p1", "name": "Alice"}},
        "interactions": [],
        "commitments": [],
        "commitments_open": [],
        "commitments_closed": [],
        "projects": [],
        "contracts": [],
        "issues": [],
        "sentiment_trend": [],
        "alerts": [],
    }

    def fake_build_view(*, stakeholder_id, from_date, to_date, include_graph):
        return payload

    monkeypatch.setattr(queries, "build_stakeholder_view", fake_build_view)

    response = client.get("/api/v1/stakeholders/p1", params={"include_graph": "true"})
    assert response.status_code == 200
    assert response.json() == payload


def test_api_v1_stakeholder_not_found(monkeypatch):
    client = TestClient(main.app)

    def fake_build_view(*, stakeholder_id, from_date, to_date, include_graph):
        return None

    monkeypatch.setattr(queries, "build_stakeholder_view", fake_build_view)

    response = client.get("/api/v1/stakeholders/missing")
    assert response.status_code == 404
