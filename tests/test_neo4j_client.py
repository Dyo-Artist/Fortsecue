import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
from logos.graphio import neo4j_client


class DummyClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def run(self, query: str, params=None):  # type: ignore[override]
        self.calls.append((query, params or {}))

    def run_in_tx(self, fn):  # pragma: no cover - not used here
        fn(None)


def test_ensure_indexes_calls_expected_cypher(monkeypatch):
    dummy = DummyClient()

    monkeypatch.setattr(neo4j_client, "_client", dummy)
    monkeypatch.setattr(neo4j_client, "_get_client", lambda: dummy)

    neo4j_client.ensure_indexes()

    expected_constraints = [
        "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Person) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Org) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Project) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Contract) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Commitment) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Interaction) REQUIRE n.id IS UNIQUE",
    ]

    constraint_calls = [c[0] for c in dummy.calls[:-1]]
    assert constraint_calls == expected_constraints
    assert "logos_name_idx" in dummy.calls[-1][0]
