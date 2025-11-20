import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from logos import main
from logos.graphio import neo4j_client


def _down(monkeypatch):
    monkeypatch.setattr(neo4j_client, "_driver", None)


def test_health_reports_down_when_no_driver(monkeypatch):
    _down(monkeypatch)
    client = TestClient(main.app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"neo4j": "down", "reason": "neo4j_unavailable"}


def test_commit_returns_503_when_graph_down(monkeypatch):
    _down(monkeypatch)
    client = TestClient(main.app)
    main.PENDING_INTERACTIONS["i1"] = {
        "interaction": {
            "type": "email",
            "at": "2024-01-01T00:00:00",
            "sentiment": 0.0,
            "summary": "hello",
            "source_uri": "uri",
        }
    }
    resp = client.post("/commit/i1")
    assert resp.status_code == 503
    assert resp.json() == {"error": "neo4j_unavailable"}


def test_search_returns_503_when_graph_down(monkeypatch):
    _down(monkeypatch)
    client = TestClient(main.app)
    resp = client.get("/search?q=x")
    assert resp.status_code == 503
    assert resp.json() == {"error": "neo4j_unavailable"}
