import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from logos import main
from logos.graphio import queries


def test_api_v1_search_returns_paginated_results(monkeypatch):
    client = TestClient(main.app)
    captured = {}

    def fake_search_fulltext(*, q, labels, org_id, project_id, page, page_size):
        captured["labels"] = labels
        captured["page"] = page
        captured["page_size"] = page_size
        return (
            [
                {"labels": ["Person"], "props": {"id": "p1", "name": "Alice"}, "score": 0.9},
                {"labels": ["Org"], "props": {"id": "o1", "name": "Acme"}, "score": 0.8},
            ],
            2,
        )

    monkeypatch.setattr(queries, "search_fulltext", fake_search_fulltext)

    response = client.get(
        "/api/v1/search",
        params={"q": "test", "type": "person,org", "page": 1, "page_size": 20},
    )

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "entity_type": "person",
                "score": 0.9,
                "person": {"id": "p1", "name": "Alice"},
            },
            {
                "entity_type": "org",
                "score": 0.8,
                "org": {"id": "o1", "name": "Acme"},
            },
        ],
        "page": 1,
        "page_size": 20,
        "total_items": 2,
        "total_pages": 1,
    }
    assert set(captured["labels"]) == {"Person", "Org"}
    assert captured["page"] == 1
    assert captured["page_size"] == 20
