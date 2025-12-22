import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from logos import main


def test_ingest_note_success() -> None:
    client = TestClient(main.app)
    payload = {
        "text": "Acme Pty Ltd will deliver the SOC2 report by 30 Sep.",
        "source_uri": "note://manual",
        "topic": "security",
    }

    resp = client.post("/ingest/note", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "interaction_id" in data
    assert data["preview_ready"] is True
    preview = data["preview"]
    assert preview["interaction"]["type"] == "note"
    assert data["interaction_id"] in main.PENDING_INTERACTIONS


def test_ingest_note_minimal_payload() -> None:
    client = TestClient(main.app)
    payload = {"text": "Quick reminder to review the SOC2 draft."}

    resp = client.post("/ingest/note", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["preview_ready"] is True
    assert data["preview"]["interaction"]["type"] == "note"
    assert data["interaction_id"] in main.PENDING_INTERACTIONS


def test_api_v1_ingest_text_aliases_note() -> None:
    client = TestClient(main.app)
    payload = {"text": "Reminder: Alex will share the timeline with Contoso."}

    resp = client.post("/api/v1/ingest/text", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["preview_ready"] is True
    assert data["interaction_id"] in main.PENDING_INTERACTIONS
    assert data["preview"]["interaction"]["type"] == "note"
