import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from logos import main


def test_alerts_lists(monkeypatch):
    client = TestClient(main.app)
    calls: list[str] = []

    def fake_run_query(query, params=None):  # type: ignore[unused-argument]
        calls.append(query)
        if "Commitment" in query:
            return [
                {
                    "id": "c1",
                    "description": "desc",
                    "due_date": "2024-01-01",
                    "status": "pending",
                    "person_id": "p1",
                    "person_name": "Alice",
                }
            ]
        return [{"org_id": "o1", "org_name": "Acme"}]

    monkeypatch.setattr(main, "run_query", fake_run_query)

    response = client.get("/alerts")
    assert response.status_code == 200
    assert response.json() == {
        "unresolved_commitments": [
            {
                "id": "c1",
                "description": "desc",
                "due_date": "2024-01-01",
                "status": "pending",
                "person_id": "p1",
                "person_name": "Alice",
            }
        ],
        "sentiment_drop": [{"org_id": "o1", "org_name": "Acme"}],
    }
    assert "MATCH (c:Commitment" in calls[0]
    assert "collect(i.sentiment)[0..3]" in calls[1]
