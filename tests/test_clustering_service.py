from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from logos.graphio.schema_store import SchemaStore
from logos.services.clustering import ClusteringService


class FakeNeo4jClient:
    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, dict]] = {
            "Particular": {
                "p1": {"id": "p1", "embedding_text": [1.0, 0.0, 0.0]},
                "p2": {"id": "p2", "embedding_text": [0.9, 0.1, 0.0]},
            },
            "Interaction": {
                "i1": {"id": "i1", "embedding_text": [0.95, 0.05, 0.0]},
                "i2": {"id": "i2", "embedding_text": [-1.0, 0.0, 0.0]},
            },
            "Concept": {
                "c1": {"id": "c1", "embedding_graph": [1.0, 0.0, 0.0]},
                "c2": {"id": "c2", "embedding_graph": [0.95, 0.1, 0.0]},
                "c3": {"id": "c3", "embedding_graph": [0.0, 1.0, 0.0]},
                "c4": {"id": "c4", "embedding_graph": [0.0, 0.95, 0.1]},
            },
        }
        self.cluster_nodes: dict[str, dict] = {}
        self.cluster_edges: list[dict] = []

    def run(self, cypher: str, params: dict | None = None):
        params = params or {}
        if "RETURN n.id AS id, n.embedding_text AS embedding" in cypher:
            label = cypher.split("MATCH (n:", 1)[1].split(")", 1)[0]
            return [
                {"id": node_id, "embedding": node["embedding_text"]}
                for node_id, node in sorted(self.nodes.get(label, {}).items())
            ]
        if "RETURN n.id AS id, n.embedding_graph AS embedding" in cypher:
            label = cypher.split("MATCH (n:", 1)[1].split(")", 1)[0]
            return [
                {"id": node_id, "embedding": node["embedding_graph"]}
                for node_id, node in sorted(self.nodes.get(label, {}).items())
            ]
        if "MERGE (c:" in cypher and "status = 'hypothesis'" in cypher:
            self.cluster_nodes[params["id"]] = dict(params)
            return []
        if "MERGE (e)-[r:" in cypher:
            self.cluster_edges.append(dict(params))
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
        "    properties: [name, embedding_graph]\n"
        "  Particular:\n"
        "    properties: [name, embedding_text]\n"
        "  Interaction:\n"
        "    properties: [summary, embedding_text]\n"
    )
    rel_types.write_text("relationship_types: {}\n")
    rules.write_text(
        "schema_conventions:\n"
        "  concept_label: Concept\n"
        "  particular_label: Particular\n"
        "  interaction_label: Interaction\n"
        "  concept_cluster_label: ConceptCluster\n"
        "  in_cluster_relationship: IN_CLUSTER\n"
    )
    version.write_text("version: 1\nlast_updated: null\n")
    return SchemaStore(node_types, rel_types, rules, version, mutable=True)


def test_clustering_service_creates_hypothesis_clusters(tmp_path: Path) -> None:
    client = FakeNeo4jClient()
    store = _schema_store(tmp_path)
    service = ClusteringService(client=client, schema_store=store)

    result = service.run(updated_at=datetime(2024, 1, 5, tzinfo=timezone.utc))

    assert result["clusters_created"] >= 2
    assert result["memberships_created"] >= 4
    assert client.cluster_nodes
    assert any(edge["algorithm"] == "hdbscan" for edge in client.cluster_edges)
    assert any(edge["algorithm"] == "leiden" for edge in client.cluster_edges)


def test_clustering_service_records_dynamic_schema_types(tmp_path: Path) -> None:
    client = FakeNeo4jClient()
    store = _schema_store(tmp_path)
    service = ClusteringService(client=client, schema_store=store)

    service.run(run_hdbscan=True, run_leiden=False, updated_at=datetime(2024, 4, 1, tzinfo=timezone.utc))

    refreshed = SchemaStore(
        node_types_path=tmp_path / "node_types.yml",
        relationship_types_path=tmp_path / "relationship_types.yml",
        rules_path=tmp_path / "rules.yml",
        version_path=tmp_path / "version.yml",
        mutable=False,
    )
    assert "ConceptCluster" in refreshed.node_types
    assert "IN_CLUSTER" in refreshed.relationship_types
