import pathlib
import sys
from datetime import datetime, timezone

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from logos import main
from logos.graphio.schema_store import SchemaStore
from logos.workflows import stages
from logos.models.bundles import InteractionMeta, PreviewBundle
from logos.staging.store import LocalStagingStore


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


def test_commit_broadcasts_updates(monkeypatch):
    client = TestClient(main.app)
    dummy_client = DummyClient()
    monkeypatch.setattr(main, "get_client", lambda: dummy_client)
    _seed_preview()

    with client.websocket_connect("/ws/updates") as websocket:
        response = client.post("/commit/i1")
        message = websocket.receive_json()

    assert response.status_code == 200
    assert message["type"] == "graph_update"
    assert message["interaction_id"] == "i1"
    assert message["summary"]["persons"] == 1


def test_commit_api_endpoint_accepts_preview_bundle(monkeypatch, tmp_path):
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
    staging_store = LocalStagingStore(tmp_path / "staging")
    monkeypatch.setattr(main, "STAGING_STORE", staging_store)

    meta = InteractionMeta(
        interaction_id="i2",
        interaction_type="email",
        source_uri="file://email",
        source_type="text",
        created_by="api",
    )
    staging_store.create_interaction(meta)
    preview_bundle = PreviewBundle(
        meta=meta,
        interaction={
            "id": "i2",
            "type": "email",
            "at": datetime(2024, 1, 1, tzinfo=timezone.utc).isoformat(),
            "sentiment": 0.0,
            "summary": "hello",
            "source_uri": "uri",
        },
        entities={
            "orgs": [{"id": "org1", "name": "Acme"}],
            "persons": [{"id": "p1", "name": "Alice", "org_id": "org1"}],
        },
        relationships=[{"src": "i2", "dst": "p1", "rel": "MENTIONS"}],
    )
    staging_store.save_preview(meta.interaction_id, preview_bundle)
    staging_store.set_state(meta.interaction_id, "preview_ready")

    response = client.post(
        "/api/v1/interactions/i2/commit",
        json=preview_bundle.model_dump(mode="json"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["interaction_id"] == "i2"
    assert staging_store.get_state("i2").state == "committed"
    assert any("MENTIONS" in cypher for cypher, _ in dummy_client.tx.calls)
