import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from logos import main
from logos.graphio import neo4j_client, queries


def test_api_v1_project_map_returns_payload(monkeypatch):
    client = TestClient(main.app)
    payload = {
        "project": {"id": "pr1", "name": "Project One", "labels": ["Project"]},
        "stakeholders": [],
        "orgs": [],
        "commitments": [],
        "issues": [],
        "risks": [],
        "project_summary": {
            "project": {"id": "pr1", "name": "Project One", "labels": ["Project"]},
            "stakeholders": [],
            "open_commitments": [],
            "issues": [],
        },
    }

    def fake_build_view(*, project_id, include_graph):
        return payload

    monkeypatch.setattr(queries, "build_project_map_view", fake_build_view)

    response = client.get("/api/v1/projects/pr1/map")

    assert response.status_code == 200
    assert response.json() == payload


def test_api_v1_project_map_not_found(monkeypatch):
    client = TestClient(main.app)

    def fake_build_view(*, project_id, include_graph):
        return None

    monkeypatch.setattr(queries, "build_project_map_view", fake_build_view)

    response = client.get("/api/v1/projects/missing/map")

    assert response.status_code == 404


def test_api_v1_project_map_reports_graph_unavailable(monkeypatch):
    client = TestClient(main.app)

    def fake_build_view(*, project_id, include_graph):
        raise neo4j_client.GraphUnavailable("neo4j_unavailable")

    monkeypatch.setattr(queries, "build_project_map_view", fake_build_view)

    response = client.get("/api/v1/projects/pr1/map")

    assert response.status_code == 503
    assert response.json() == {"error": "neo4j_unavailable"}
