import pathlib
import sys
from datetime import datetime, timezone

import yaml

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from logos.graphio.schema_store import SchemaStore
from logos.graphio.upsert import (
    GraphNode,
    GraphRelationship,
    InteractionBundle,
    upsert_interaction_bundle,
    upsert_node,
    upsert_relationship,
)


class FakeTx:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def run(self, cypher: str, params: dict | None = None):
        self.calls.append((cypher, params or {}))
        return []


def _temp_schema(tmp_path) -> SchemaStore:
    node_path = tmp_path / "node_types.yml"
    rel_path = tmp_path / "relationship_types.yml"
    rules_path = tmp_path / "rules.yml"
    version_path = tmp_path / "version.yml"
    rules_path.write_text("usage_deprecation:\n  min_usage: 1\n  stale_after_days: 180\n")
    version_path.write_text("version: 1\nlast_updated: null\n")
    return SchemaStore(node_path, rel_path, rules_path, version_path)


def test_upsert_node_records_schema_and_concept_link(tmp_path):
    tx = FakeTx()
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    store = _temp_schema(tmp_path)
    node = GraphNode(
        id="p1",
        label="Person",
        properties={"name": "Alice", "org_id": "org1"},
        concept_id="stakeholder_type_community",
        concept_kind="StakeholderType",
        source_uri="src",
    )

    upsert_node(tx, node, now, schema_store=store)

    assert len(tx.calls) == 3  # node, concept node, instance_of
    cypher, params = tx.calls[0]
    assert "Person" in cypher
    assert params["id"] == "p1"
    concept_rel = next(call for call in tx.calls if "INSTANCE_OF" in call[0])
    assert concept_rel[1]["src"] == "p1"
    node_types = yaml.safe_load((tmp_path / "node_types.yml").read_text())["node_types"]
    assert "Person" in node_types
    assert node_types["Person"]["usage_count"] == 1


def test_upsert_relationship_accepts_dynamic_type(tmp_path):
    tx = FakeTx()
    now = datetime(2024, 2, 1, tzinfo=timezone.utc)
    store = _temp_schema(tmp_path)
    rel = GraphRelationship(src="a1", dst="b1", rel="COLLABORATES_WITH", properties={"weight": 0.7})

    upsert_relationship(tx, rel, "source://dynamic", now, schema_store=store)

    cypher, params = tx.calls[0]
    assert "COLLABORATES_WITH" in cypher
    assert params["src"] == "a1"
    rel_types = yaml.safe_load((tmp_path / "relationship_types.yml").read_text())["relationship_types"]
    assert "COLLABORATES_WITH" in rel_types
    assert rel_types["COLLABORATES_WITH"]["usage_count"] == 1


def test_upsert_node_merges_by_id_only(tmp_path):
    tx = FakeTx()
    now = datetime(2024, 2, 1, tzinfo=timezone.utc)
    store = _temp_schema(tmp_path)
    node = GraphNode(
        id="person-1",
        label="Person",
        properties={"name": "Ada", "title": "Engineer"},
        source_uri="source://test",
    )

    upsert_node(tx, node, now, schema_store=store)

    cypher, params = tx.calls[0]
    assert "MERGE (n:Person {id: $id})" in cypher
    assert params["id"] == "person-1"
    assert "MERGE (n:Person {name" not in cypher


def test_upsert_relationship_matches_nodes_by_id(tmp_path):
    tx = FakeTx()
    now = datetime(2024, 2, 1, tzinfo=timezone.utc)
    store = _temp_schema(tmp_path)
    rel = GraphRelationship(src="src-123", dst="dst-456", rel="MENTIONS", src_label="Interaction", dst_label="Topic")

    upsert_relationship(tx, rel, "source://mention", now, schema_store=store)

    cypher, params = tx.calls[0]
    assert "MATCH (src:Interaction {id: $src})" in cypher
    assert "MATCH (dst:Topic {id: $dst})" in cypher
    assert "MERGE (src)-[r:MENTIONS]->(dst)" in cypher
    assert params["src"] == "src-123"
    assert params["dst"] == "dst-456"


def test_upsert_interaction_bundle_handles_dynamic_nodes(tmp_path):
    tx = FakeTx()
    now = datetime(2024, 3, 1, tzinfo=timezone.utc)
    store = _temp_schema(tmp_path)
    interaction = GraphNode(
        id="i1",
        label="Interaction",
        properties={"type": "email"},
        concept_id="interaction_email",
        concept_kind="InteractionType",
        source_uri="src",
    )
    milestone = GraphNode(id="m1", label="Milestone", properties={"name": "Design freeze"}, source_uri="src")
    relationships = [
        GraphRelationship(src="i1", dst="m1", rel="MENTIONS", src_label="Interaction", dst_label="Milestone"),
    ]
    bundle = InteractionBundle(interaction=interaction, nodes=[milestone], relationships=relationships)

    upsert_interaction_bundle(tx, bundle, now, schema_store=store)

    cypher_statements = [call[0] for call in tx.calls]
    assert any("Milestone" in stmt for stmt in cypher_statements)
    assert any("MENTIONS" in stmt for stmt in cypher_statements)
    node_types = yaml.safe_load((tmp_path / "node_types.yml").read_text())["node_types"]
    assert "Milestone" in node_types


def test_upsert_interaction_bundle_defaults_missing_source(tmp_path):
    tx = FakeTx()
    now = datetime(2024, 4, 1, tzinfo=timezone.utc)
    store = _temp_schema(tmp_path)
    interaction = GraphNode(
        id="i2",
        label="Interaction",
        properties={},
        concept_kind="InteractionType",
    )
    node = GraphNode(id="p2", label="Person", properties={"name": "Test"})
    relationship = GraphRelationship(
        src="i2",
        dst="p2",
        rel="MENTIONS",
        src_label="Interaction",
        dst_label="Person",
    )
    bundle = InteractionBundle(interaction=interaction, nodes=[node], relationships=[relationship])

    upsert_interaction_bundle(tx, bundle, now, schema_store=store)

    default_source_uri = f"interaction://{interaction.id}"
    node_call = tx.calls[0][1]
    assert node_call["source_uri"] == default_source_uri
    rel_call = next(call[1] for call in tx.calls if "MERGE (src)-[r" in call[0])
    assert rel_call["source_uri"] == default_source_uri
