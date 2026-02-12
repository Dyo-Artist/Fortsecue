from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from logos.graphio.schema_store import SchemaStore
from logos.services.embeddings import EmbeddingService, LocalSentenceEmbeddingBackend, Node2VecGraphEmbeddingBackend


class FakeNeo4jClient:
    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, dict]] = {
            "Concept": {
                "c1": {"id": "c1", "name": "Stakeholder", "kind": "StakeholderType"},
                "c2": {"id": "c2", "name": "Project", "kind": "ProjectType"},
                "c3": {"id": "c3", "name": "Risk", "kind": "RiskCategory"},
            },
            "Person": {
                "p1": {"id": "p1", "name": "Alice", "title": "Engineer"},
            },
            "Interaction": {
                "i1": {"id": "i1", "summary": "Weekly sync about project risk"},
            },
        }
        self.concept_edges = [("c1", "c2"), ("c2", "c3")]
        self.write_calls: list[tuple[str, dict]] = []

    def run(self, cypher: str, params: dict | None = None):
        params = params or {}
        if "RETURN n.id AS id, properties(n) AS props" in cypher:
            label = cypher.split("MATCH (n:", 1)[1].split(")", 1)[0]
            return [
                {"id": node_id, "props": dict(props)}
                for node_id, props in sorted(self.nodes.get(label, {}).items())
            ]
        if "RETURN a.id AS src, b.id AS dst" in cypher:
            return [{"src": src, "dst": dst} for src, dst in self.concept_edges]
        if "SET n.embedding" in cypher:
            label = cypher.split("MATCH (n:", 1)[1].split(" ", 1)[0]
            node_id = params["id"]
            node = self.nodes[label][node_id]
            if "embedding_text" in cypher:
                node["embedding_text"] = params["embedding"]
                node["embedding_text_model"] = params["embedding_model"]
            if "embedding_graph" in cypher:
                node["embedding_graph"] = params["embedding"]
                node["embedding_graph_model"] = params["embedding_model"]
            node["embedding_model"] = params["embedding_model"]
            node["embedding_updated_at"] = params["embedding_updated_at"]
            self.write_calls.append((cypher, params))
            return []
        raise AssertionError(f"Unexpected query: {cypher}")


def _schema_store(tmp_path: Path) -> SchemaStore:
    node_types = tmp_path / "node_types.yml"
    rel_types = tmp_path / "relationship_types.yml"
    rules = tmp_path / "rules.yml"
    version = tmp_path / "version.yml"

    node_types.write_text(
        "node_types:\n"
        "  Concept:\n"
        "    properties: [name, kind]\n"
        "  Person:\n"
        "    properties: [name, title]\n"
        "  Interaction:\n"
        "    properties: [summary]\n"
    )
    rel_types.write_text("relationship_types: {}\n")
    rules.write_text("schema_conventions:\n  concept_label: Concept\n")
    version.write_text("version: 1\nlast_updated: null\n")
    return SchemaStore(node_types, rel_types, rules, version, mutable=False)


def test_embedding_service_writes_text_and_graph_embeddings(tmp_path: Path) -> None:
    client = FakeNeo4jClient()
    store = _schema_store(tmp_path)
    service = EmbeddingService(
        client=client,
        schema_store=store,
        text_backend=LocalSentenceEmbeddingBackend(dimensions=12),
        graph_backend=Node2VecGraphEmbeddingBackend(dimensions=12, seed=7),
    )

    result = service.refresh_embeddings(seed=7, updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc))

    assert result["text_embeddings_updated"] == 5
    assert result["graph_embeddings_updated"] == 3
    assert "embedding_text" in client.nodes["Person"]["p1"]
    assert "embedding_text" in client.nodes["Interaction"]["i1"]
    assert "embedding_graph" in client.nodes["Concept"]["c1"]
    assert client.nodes["Concept"]["c1"]["embedding_model"] == result["graph_embedding_model"]


def test_embedding_service_is_idempotent_for_fixed_seed(tmp_path: Path) -> None:
    client = FakeNeo4jClient()
    store = _schema_store(tmp_path)
    service = EmbeddingService(
        client=client,
        schema_store=store,
        text_backend=LocalSentenceEmbeddingBackend(dimensions=10),
        graph_backend=Node2VecGraphEmbeddingBackend(dimensions=10, seed=19),
    )

    now = datetime(2024, 3, 1, tzinfo=timezone.utc)
    first = service.refresh_embeddings(seed=19, updated_at=now)
    writes_after_first = len(client.write_calls)
    second = service.refresh_embeddings(seed=19, updated_at=now)

    assert first["text_embeddings_updated"] > 0
    assert first["graph_embeddings_updated"] > 0
    assert second["text_embeddings_updated"] == 0
    assert second["graph_embeddings_updated"] == 0
    assert len(client.write_calls) == writes_after_first
