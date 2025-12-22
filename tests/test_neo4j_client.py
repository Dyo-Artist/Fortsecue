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

    schema_store = neo4j_client.SchemaStore(mutable=False)
    expected_labels = set(schema_store.node_types.keys())

    constraint_calls = [c[0] for c in dummy.calls if c[0].startswith("CREATE CONSTRAINT")]
    assert expected_labels == {
        call.split(":", maxsplit=1)[1].split(")", maxsplit=1)[0] for call in constraint_calls
    }

    name_index_labels = {label for label, definition in schema_store.node_types.items() if "name" in definition.properties}
    if name_index_labels:
        assert any("logos_name_idx" in call[0] for call in dummy.calls)
