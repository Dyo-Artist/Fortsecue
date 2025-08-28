"""Tests for the document ingestion preview endpoint."""

from fastapi.testclient import TestClient

from logos.app import PREVIEWS, app


client = TestClient(app)


def test_ingest_doc_preview_shape() -> None:
    """Posting a document returns a correctly shaped preview."""

    payload = {
        "source_uri": "s1",
        "text": "Alice Smith will sign the contract with Acme Corp.",
    }
    response = client.post("/ingest/doc", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert set(data.keys()) == {"entities", "relationships", "interaction"}
    entities = data["entities"]
    assert set(entities.keys()) == {"persons", "orgs", "commitments", "projects"}

    assert entities["persons"], "expected at least one person"
    assert entities["orgs"], "expected at least one org"
    assert entities["commitments"], "expected at least one commitment"

    interaction = data["interaction"]
    assert {
        "id",
        "type",
        "at",
        "sentiment",
        "summary",
        "source_uri",
    }.issubset(interaction.keys())
    assert interaction["source_uri"] == payload["source_uri"]
    assert interaction["id"] in PREVIEWS

