import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from logos import main
from logos.graphio import queries as graph_queries


def test_api_v1_alerts_filters(monkeypatch):
    client = TestClient(main.app)
    captured: dict[str, object] = {}

    def fake_list_alerts(
        *,
        types=None,
        statuses=None,
        project_id=None,
        stakeholder_id=None,
        org_id=None,
        page=1,
        page_size=20,
    ):
        captured.update(
            {
                "types": types,
                "statuses": statuses,
                "project_id": project_id,
                "stakeholder_id": stakeholder_id,
                "org_id": org_id,
                "page": page,
                "page_size": page_size,
            }
        )
        return (
            [
                {
                    "id": "a1",
                    "type": "unresolved_commitment",
                    "status": "open",
                }
            ],
            12,
        )

    monkeypatch.setattr(graph_queries, "list_alerts", fake_list_alerts)

    response = client.get(
        "/api/v1/alerts"
        "?type=unresolved_commitment"
        "&status=open"
        "&project_id=pr1"
        "&stakeholder_id=st1"
        "&org_id=o1"
        "&page=2"
        "&page_size=5"
    )

    assert response.status_code == 200
    assert captured == {
        "types": ["unresolved_commitment"],
        "statuses": ["open"],
        "project_id": "pr1",
        "stakeholder_id": "st1",
        "org_id": "o1",
        "page": 2,
        "page_size": 5,
    }
    assert response.json() == {
        "items": [
            {
                "id": "a1",
                "type": "unresolved_commitment",
                "status": "open",
            }
        ],
        "page": 2,
        "page_size": 5,
        "total_items": 12,
        "total_pages": 3,
    }
