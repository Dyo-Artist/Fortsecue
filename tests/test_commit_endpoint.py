import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from logos import main


def test_commit_endpoint_writes_preview(monkeypatch):
    client = TestClient(main.app)
    main.PENDING_INTERACTIONS["i1"] = {
        "interaction": {
            "id": "i1",
            "type": "email",
            "at": "2024-01-01T00:00:00",
            "sentiment": 0.0,
            "summary": "hello",
            "source_uri": "uri",
        },
        "entities": {
            "orgs": [{"id": "org1", "name": "Acme"}],
            "persons": [{"id": "p1", "name": "Alice", "org_id": "org1"}],
            "projects": [{"id": "proj1", "name": "Project One"}],
            "contracts": [{"id": "ct1", "name": "Contract"}],
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
            {"src": "p1", "dst": "org1", "rel": "WORKS_FOR"},
            {"src": "p1", "dst": "proj1", "rel": "INVOLVED_IN"},
            {"src": "org1", "dst": "ct1", "rel": "PARTY_TO"},
            {"src": "i1", "dst": "p1", "rel": "MENTIONS"},
        ],
    }

    calls = []

    def _rec(name):
        def _record(*args, **kwargs):
            calls.append((name, args, kwargs))

        return _record

    monkeypatch.setattr(main, "upsert_org", _rec("upsert_org"))
    monkeypatch.setattr(main, "upsert_person", _rec("upsert_person"))
    monkeypatch.setattr(main, "upsert_project", _rec("upsert_project"))
    monkeypatch.setattr(main, "upsert_contract", _rec("upsert_contract"))
    monkeypatch.setattr(main, "upsert_topic", _rec("upsert_topic"))
    monkeypatch.setattr(main, "upsert_commitment", _rec("upsert_commitment"))
    monkeypatch.setattr(main, "upsert_interaction", _rec("upsert_interaction"))
    monkeypatch.setattr(main, "upsert_relationship", _rec("upsert_relationship"))

    response = client.post("/commit/i1")

    assert response.status_code == 200
    assert response.json() == {"status": "committed", "interaction_id": "i1"}
    assert "i1" not in main.PENDING_INTERACTIONS

    names = [call[0] for call in calls]
    assert names[:7] == [
        "upsert_org",
        "upsert_person",
        "upsert_project",
        "upsert_contract",
        "upsert_topic",
        "upsert_commitment",
        "upsert_interaction",
    ]
    assert names[7:] == ["upsert_relationship"] * 4

    assert calls[0][1] == ("org1", "Acme")
    assert calls[1][1] == ("p1", "Alice")
    assert calls[2][1] == ("proj1", "Project One")
    assert calls[5][1] == ("c1", "Do it", "p1")
    assert calls[6][1][0] == "i1"


def test_commit_endpoint_returns_404_for_missing_preview():
    client = TestClient(main.app)
    response = client.post("/commit/unknown")
    assert response.status_code == 404
    assert response.json() == {"detail": "interaction not found"}
