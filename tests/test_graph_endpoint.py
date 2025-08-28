import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from logos import main


def test_ego_graph_returns_expected_keys(monkeypatch):
    client = TestClient(main.app)

    fake_result = [
        {
            "pnodes": [{"id": "p1"}],
            "nodes": [{"id": "p2"}],
            "edges": [{"source": "p1", "target": "p2", "type": "KNOWS"}],
        }
    ]

    def fake_run_query(query, params):
        return fake_result

    monkeypatch.setattr(main, "run_query", fake_run_query)

    response = client.get("/graph/ego", params={"person_id": "p1"})
    assert response.status_code == 200
    data = response.json()
    assert set(data.keys()) == {"pnodes", "nodes", "edges"}
