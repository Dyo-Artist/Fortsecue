import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from logos import main


def test_commit_endpoint_writes_preview(monkeypatch):
    client = TestClient(main.app)
    main.PREVIEWS["i1"] = {
        "interaction": {
            "type": "email",
            "at": "2024-01-01T00:00:00",
            "sentiment": 0.0,
            "summary": "hello",
            "source_uri": "uri",
        }
    }

    called = {}

    def fake_upsert(interaction_id, type_, at, sentiment, summary, source_uri, mention_ids=None):
        called["interaction_id"] = interaction_id
        called["type"] = type_
        called["at"] = at
        called["sentiment"] = sentiment
        called["summary"] = summary
        called["source_uri"] = source_uri
        called["mention_ids"] = mention_ids

    monkeypatch.setattr(main, "upsert_interaction", fake_upsert)
    response = client.post("/commit/i1")

    assert response.status_code == 200
    assert called == {
        "interaction_id": "i1",
        "type": "email",
        "at": "2024-01-01T00:00:00",
        "sentiment": 0.0,
        "summary": "hello",
        "source_uri": "uri",
        "mention_ids": None,
    }
