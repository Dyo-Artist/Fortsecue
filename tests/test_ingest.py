import os
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app.main import PREVIEWS, app


def test_ingest_doc_preview():
    client = TestClient(app)
    doc = {
        "source_uri": "http://example.com",
        "text": "Alice from Acme Corp commits to build new AI project.",
    }
    resp = client.post("/ingest/doc", json=doc)
    assert resp.status_code == 200
    data = resp.json()

    assert len(data["entities"]["persons"]) >= 1
    assert len(data["entities"]["orgs"]) >= 1
    assert len(data["entities"]["commitments"]) >= 1
    assert data["interaction"]["source_uri"] == doc["source_uri"]
    assert data["interaction"]["id"] in PREVIEWS
