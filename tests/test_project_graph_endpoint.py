import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from logos import main
from logos.graphio import neo4j_client


def _down(monkeypatch):
    def _raise():
        raise neo4j_client.GraphUnavailable("neo4j_unavailable")

    monkeypatch.setattr(neo4j_client, "_client", None)
    monkeypatch.setattr(neo4j_client, "_get_client", _raise)


def test_project_graph_returns_503_when_graph_down(monkeypatch):
    _down(monkeypatch)
    client = TestClient(main.app)

    response = client.get("/graph/project", params={"project_id": "p1"})

    assert response.status_code == 503
    assert response.json() == {"error": "neo4j_unavailable"}


def test_project_graph_proxies_project_map(monkeypatch):
    client = TestClient(main.app)

    fake_map = {
        "nodes": [
            {"id": "proj1", "labels": ["Project"]},
            {"id": "commit1", "labels": ["Commitment"]},
        ],
        "edges": [
            {"src": "commit1", "dst": "proj1", "rel": "RELATES_TO"},
        ],
    }

    def fake_project_map(project_id):
        return fake_map

    monkeypatch.setattr(main, "project_map", fake_project_map)

    response = client.get("/graph/project", params={"project_id": "proj1"})

    assert response.status_code == 200
    assert response.json() == fake_map
