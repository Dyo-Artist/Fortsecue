import pathlib
import sys
from datetime import datetime, timezone

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from logos import main
from logos.graphio.schema_store import SchemaStore
from logos.workflows import stages


class DummyTx:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def run(self, cypher: str, params=None):
        self.calls.append((cypher, params or {}))


class DummyClient:
    def __init__(self) -> None:
        self.tx = DummyTx()
        self.queries: list[tuple[str, dict]] = []

    def run_in_tx(self, fn):
        fn(self.tx)

    def run(self, cypher: str, params=None):
        self.queries.append((cypher, params or {}))
        return []


def _seed_preview():
    main.PENDING_INTERACTIONS["i1"] = {
        "interaction": {
            "id": "i1",
            "type": "email",
            "at": datetime(2024, 1, 1, tzinfo=timezone.utc).isoformat(),
            "sentiment": 0.0,
            "summary": "hello",
            "source_uri": "uri",
        },
        "entities": {
            "orgs": [{"id": "org1", "name": "Acme"}],
            "persons": [{"id": "p1", "name": "Alice", "org_id": "org1"}],
            "projects": [{"id": "proj1", "name": "Project One"}],
            "contracts": [{"id": "ct1", "name": "Contract", "org_ids": ["org1"]}],
            "topics": ["Topic A"],
            "commitments": [
                {
                    "id": "c1",
                    "text": "Do it",
                    "person_id": "p1",
                    "relates_to_project_id": "proj1",
                }
            ],
        },
        "relationships": [
            {"src": "p1", "dst": "proj1", "rel": "INVOLVED_IN"},
            {"src": "i1", "dst": "p1", "rel": "MENTIONS"},
        ],
    }


def test_commit_endpoint_runs_upsert_bundle(monkeypatch, tmp_path):
    client = TestClient(main.app)
    dummy_client = DummyClient()
    monkeypatch.setattr(main, "get_client", lambda: dummy_client)
    tmp_schema = SchemaStore(
        tmp_path / "node_types.yml",
        tmp_path / "relationship_types.yml",
        tmp_path / "rules.yml",
        tmp_path / "version.yml",
    )
    monkeypatch.setattr(stages, "SCHEMA_STORE", tmp_schema)
    _seed_preview()

    response = client.post("/commit/i1")

    assert response.status_code == 200
    body = response.json()
    assert body["interaction_id"] == "i1"
    assert body["counts"]["persons"] == 1
    assert any("MENTIONS" in cypher for cypher, _ in dummy_client.tx.calls)
    assert any(call[1].get("props", {}).get("org_id") == "org1" for call in dummy_client.tx.calls)
    assert "i1" not in main.PENDING_INTERACTIONS


def test_commit_endpoint_returns_404_for_missing_preview():
    client = TestClient(main.app)
    response = client.post("/commit/unknown")
    assert response.status_code == 404
    assert response.json() == {"detail": "interaction not found"}
