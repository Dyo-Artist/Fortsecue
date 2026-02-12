from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from logos.graphio.schema_store import SchemaStore
from logos.learning.clustering.cluster_engine import ClusterEngine


class FakeNeo4jClient:
    def __init__(self) -> None:
        self.concepts: dict[str, dict] = {}
        self.relationships: list[dict] = []
        self.promotions: list[dict] = []

    def run(self, cypher: str, params: dict | None = None):
        params = params or {}
        if "MERGE (c:" in cypher and "c.status = 'proposed'" in cypher:
            self.concepts[params["id"]] = dict(params)
            return []
        if "MERGE (p)-[r:" in cypher and "CANDIDATE_INSTANCE_OF" in cypher:
            self.relationships.append(dict(params))
            return []
        if "SET c.status = 'canonical'" in cypher:
            self.promotions.append(dict(params))
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
        "    properties: [status, parent_form, provenance]\n"
        "  Particular:\n"
        "    properties: [name]\n"
    )
    rel_types.write_text("relationship_types: {}\n")
    rules.write_text(
        "schema_conventions:\n"
        "  concept_label: Concept\n"
        "  particular_label: Particular\n"
        "  candidate_instance_of_relationship: CANDIDATE_INSTANCE_OF\n"
    )
    version.write_text("version: 1\nlast_updated: null\n")
    return SchemaStore(node_types, rel_types, rules, version, mutable=True)


def test_cluster_governance_creates_only_proposed_concepts_for_new_terms(tmp_path: Path) -> None:
    client = FakeNeo4jClient()
    store = _schema_store(tmp_path)
    engine = ClusterEngine(client=client, schema_store=store)

    synthetic_terms = [f"new-term-{idx:02d}" for idx in range(20)]
    proposed = engine.propose_concept_from_cluster(
        cluster_id="cluster-synthetic-20",
        parent_form="Form:Stakeholder",
        particular_ids=synthetic_terms,
        algorithm="hdbscan",
        created_at=datetime(2024, 5, 20, tzinfo=timezone.utc),
        provenance={"dataset": "synthetic-governance"},
    )

    concept = client.concepts[proposed.concept_id]
    assert proposed.status == "proposed"
    assert concept["parent_form"] == "Form:Stakeholder"
    assert concept["provenance"]["cluster_id"] == "cluster-synthetic-20"
    assert concept["provenance"]["dataset"] == "synthetic-governance"

    assert len(client.relationships) == 20
    assert all(rel["concept_id"] == proposed.concept_id for rel in client.relationships)

    promoted = engine.promote_proposed_concept(
        concept_id=proposed.concept_id,
        manual_trigger=False,
        promoted_by="auto-cluster",
    )
    assert promoted is False
    assert client.promotions == []


def test_cluster_governance_uses_candidate_instance_relationship(tmp_path: Path) -> None:
    client = FakeNeo4jClient()
    store = _schema_store(tmp_path)
    engine = ClusterEngine(client=client, schema_store=store)

    proposed = engine.propose_concept_from_cluster(
        cluster_id="cluster-links",
        parent_form="Form:Topic",
        particular_ids=["p-1", "p-2"],
        algorithm="leiden",
        created_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
    )

    assert proposed.status == "proposed"
    assert len(client.relationships) == 2

    refreshed = SchemaStore(
        node_types_path=tmp_path / "node_types.yml",
        relationship_types_path=tmp_path / "relationship_types.yml",
        rules_path=tmp_path / "rules.yml",
        version_path=tmp_path / "version.yml",
        mutable=False,
    )
    assert "CANDIDATE_INSTANCE_OF" in refreshed.relationship_types
