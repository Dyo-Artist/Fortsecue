import pathlib
import sys
from datetime import datetime, timezone

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from logos.normalise import build_interaction_bundle
from logos.services.sync import build_graph_update_event


def test_build_graph_update_event_from_bundle():
    preview = {
        "interaction": {
            "id": "i-sync",
            "type": "note",
            "at": datetime(2024, 1, 2, tzinfo=timezone.utc).isoformat(),
            "summary": "summary",
            "source_uri": "uri",
        },
        "entities": {
            "stakeholder_types": [{"id": "st_contract", "name": "Contractor"}],
            "orgs": [{"id": "org1", "name": "Acme"}],
            "persons": [{"id": "p1", "name": "Alice", "org_id": "org1", "type": "Contractor"}],
            "topics": [{"id": "topic1", "name": "Safety"}],
        },
        "relationships": [
            {"src": "i-sync", "dst": "p1", "rel": "MENTIONS"},
        ],
    }
    bundle = build_interaction_bundle("i-sync", preview)
    event = build_graph_update_event(bundle, datetime(2024, 1, 2, 10, tzinfo=timezone.utc))
    payload = event.model_dump(mode="json")

    assert payload["type"] == "graph_update"
    assert payload["interaction_id"] == "i-sync"
    assert payload["entities"]["orgs"][0]["id"] == "org1"
    assert payload["summary"]["persons"] == 1
    assert payload["summary"]["relationships"] == 1
    assert str(payload["committed_at"]).startswith("2024-01-02T10:00:00")
