import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from logos import main


def test_search_endpoint_returns_results(monkeypatch):
    client = TestClient(main.app)

    fake_results = [
        {"labels": ["Person"], "id": "p1", "name": "Alice", "score": 0.9},
        {"labels": ["Org"], "id": "o1", "name": "Acme", "score": 0.8},
    ]

    captured = {}

    def fake_run_query(query, params):
        captured["query"] = query
        captured["params"] = params
        return fake_results

    monkeypatch.setattr(main, "run_query", fake_run_query)

    response = client.get("/search?q=test")
    assert response.status_code == 200
    assert response.json() == fake_results
    assert "logos_name_idx" in captured["query"]
    assert captured["params"] == {"q": "test"}
