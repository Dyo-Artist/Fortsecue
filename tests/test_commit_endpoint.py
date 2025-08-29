import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from logos import main


def test_commit_endpoint_writes_preview(monkeypatch):
    client = TestClient(main.app)
    main.PREVIEWS["i1"] = {"interaction": {"summary": "hello"}}

    called = {}

    def fake_upsert(interaction_id, preview):
        called["interaction_id"] = interaction_id
        called["preview"] = preview

    monkeypatch.setattr(main, "upsert_interaction", fake_upsert)
    response = client.post("/commit/i1")

    assert response.status_code == 200
    assert called == {"interaction_id": "i1", "preview": "hello"}
