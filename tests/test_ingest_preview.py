from fastapi.testclient import TestClient

from logos.app import app


client = TestClient(app)


def test_ingest_preview() -> None:
    response = client.get("/ingest/preview")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
