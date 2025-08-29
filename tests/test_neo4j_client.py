import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
from logos.graphio import neo4j_client



def test_ensure_indexes_calls_expected_cypher(monkeypatch):
    calls: list[str] = []

    def fake_run_query(query: str, params=None):  # type: ignore[unused-argument]
        calls.append(query)

    monkeypatch.setattr(neo4j_client, "run_query", fake_run_query)
    monkeypatch.setattr(neo4j_client, "_driver", object())
    neo4j_client.ensure_indexes()

    expected = [
        "CREATE CONSTRAINT person_id IF NOT EXISTS FOR (n:Person) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT org_id IF NOT EXISTS FOR (n:Org) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT project_id IF NOT EXISTS FOR (n:Project) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT contract_id IF NOT EXISTS FOR (n:Contract) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT commitment_id IF NOT EXISTS FOR (n:Commitment) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT interaction_id IF NOT EXISTS FOR (n:Interaction) REQUIRE n.id IS UNIQUE",
        "CALL db.index.fulltext.createNodeIndex('logos_name_idx', ['Person','Org','Project','Contract','Commitment'], ['name'], { ifNotExists: true })",
    ]

    assert calls == expected
