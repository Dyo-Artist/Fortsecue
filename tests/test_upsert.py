import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
from logos.graphio import upsert



def test_upsert_org(monkeypatch):
    captured = {}

    def fake_run_query(query, params):
        captured["query"] = query
        captured["params"] = params

    monkeypatch.setattr(upsert, "run_query", fake_run_query)
    upsert.upsert_org("org1", "Acme")
    assert captured["query"] == "MERGE (o:Org {id: $id}) SET o.name = $name"
    assert captured["params"] == {"id": "org1", "name": "Acme"}


def test_upsert_person_with_org(monkeypatch):
    captured = {}

    def fake_run_query(query, params):
        captured["query"] = query
        captured["params"] = params

    monkeypatch.setattr(upsert, "run_query", fake_run_query)
    upsert.upsert_person("p1", "Alice", org_id="org1")
    assert (
        captured["query"]
        == "MERGE (p:Person {id: $id}) SET p.name = $name MERGE (o:Org {id: $org_id}) MERGE (p)-[:WORKS_FOR]->(o)"
    )
    assert captured["params"] == {"id": "p1", "name": "Alice", "org_id": "org1"}


def test_upsert_interaction_mentions(monkeypatch):
    captured = {}

    def fake_run_query(query, params):
        captured["query"] = query
        captured["params"] = params

    monkeypatch.setattr(upsert, "run_query", fake_run_query)
    upsert.upsert_interaction(
        "i1",
        "email",
        "2024-01-01T00:00:00",
        0.1,
        "hello",
        "uri",
        ["p1", "p2"],
    )
    assert (
        captured["query"]
        == "MERGE (i:Interaction {id: $id}) SET i.type=$type, i.at=datetime($at), i.sentiment=$sentiment, i.summary=$summary, i.source_uri=$source_uri, i.last_seen=datetime() WITH i UNWIND $mention_ids AS mid MERGE (p:Person {id: mid}) MERGE (i)-[:MENTIONS]->(p)"
    )
    assert captured["params"] == {
        "id": "i1",
        "type": "email",
        "at": "2024-01-01T00:00:00",
        "sentiment": 0.1,
        "summary": "hello",
        "source_uri": "uri",
        "mention_ids": ["p1", "p2"],
    }


def test_upsert_commitment(monkeypatch):
    captured = {}

    def fake_run_query(query, params):
        captured["query"] = query
        captured["params"] = params

    monkeypatch.setattr(upsert, "run_query", fake_run_query)
    upsert.upsert_commitment("c1", "Do it", "p1")
    assert captured["query"] == (
        "MERGE (c:Commitment {id: $id}) SET c.text = $text, c.status = $status, c.last_seen = datetime() "
        "MERGE (p:Person {id: $person_id}) MERGE (p)-[:MADE]->(c)"
    )
    assert captured["params"] == {"id": "c1", "text": "Do it", "status": "open", "person_id": "p1"}
