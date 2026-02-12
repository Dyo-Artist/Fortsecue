from __future__ import annotations

import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from logos import main
from logos.api.routes import ingest as ingest_routes


class DummyTx:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def run(self, cypher: str, params=None):
        self.calls.append((cypher, params or {}))


class DummyClient:
    def __init__(self) -> None:
        self.tx = DummyTx()

    def run_in_tx(self, fn):
        fn(self.tx)


def test_ingest_preview_commit_round_trip(monkeypatch) -> None:
    client = TestClient(main.app)
    dummy_client = DummyClient()
    monkeypatch.setattr(ingest_routes, "get_client", lambda: dummy_client)

    ingest_response = client.post(
        "/api/v1/ingest/text",
        json={"text": "Jordan to deliver revised plan to Acme next week."},
    )
    assert ingest_response.status_code == 200
    ingest_payload = ingest_response.json()
    interaction_id = ingest_payload["interaction_id"]

    preview_response = client.get(f"/api/v1/interactions/{interaction_id}/preview")
    assert preview_response.status_code == 200
    preview_payload = preview_response.json()

    commit_response = client.post(
        f"/api/v1/interactions/{interaction_id}/commit",
        json=preview_payload,
    )
    assert commit_response.status_code == 200
    commit_payload = commit_response.json()

    assert commit_payload["interaction_id"] == interaction_id
    assert commit_payload["status"] == "committed"
    assert any("MERGE" in cypher for cypher, _ in dummy_client.tx.calls)
