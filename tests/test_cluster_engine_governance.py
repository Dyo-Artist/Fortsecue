from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from logos.graphio.schema_store import SchemaStore
from logos.learning.clustering.cluster_engine import ClusterEngine
from logos.learning.clustering.concept_governance import ConceptGovernance, ConceptPromotionError


class FakeNeo4jClient:
    def __init__(self) -> None:
        self.concepts: dict[str, dict] = {}
        self.relationships: list[dict] = []
        self.promotions: list[dict] = []

    def run(self, cypher: str, params: dict | None = None):
        params = params or {}
        if "MERGE (c:" in cypher and "c.status = 'proposed'" in cypher:
            self.concepts[params["id"]] = {"status": "proposed", **dict(params)}
            return []
        if "MERGE (p)-[r:" in cypher and "CANDIDATE_INSTANCE_OF" in cypher:
            self.relationships.append(dict(params))
            return []
        if "RETURN c.status AS status" in cypher:
            concept = self.concepts.get(params["concept_id"])
            return [{"status": concept.get("status")}] if concept else []
        if "DELETE candidate" in cypher and "RETURN count(inst) AS converted_count" in cypher:
            concept_id = params["concept_id"]
            converted = sum(1 for rel in self.relationships if rel.get("concept_id") == concept_id)
            return [{"converted_count": converted}]
        if "SET c.status = 'canonical'" in cypher:
            concept = self.concepts.get(params["concept_id"])
            if concept:
                concept["status"] = "canonical"
            self.promotions.append(dict(params))
            return []
        if "RETURN c.id AS id" in cypher:
            concept = self.concepts.get(params["concept_id"])
            return [{"id": params["concept_id"]}] if concept else []
        if "RETURN count(moved) AS repointed_count" in cypher:
            source_id = params["source_concept_id"]
            moved = 0
            for rel in self.relationships:
                if rel.get("concept_id") == source_id:
                    rel["concept_id"] = params["target_concept_id"]
                    moved += 1
            return [{"repointed_count": moved}]
        if "SET c.status = 'merged'" in cypher:
            concept = self.concepts.get(params["source_concept_id"])
            if concept:
                concept["status"] = "merged"
                concept["merged_into"] = params["target_concept_id"]
            return []
        if "SET c.status = 'rejected'" in cypher:
            concept = self.concepts.get(params["concept_id"])
            if concept:
                concept["status"] = "rejected"
                concept["rejection_provenance"] = params["rejection_provenance"]
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
        "  instance_of_relationship: INSTANCE_OF\n"
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


def test_concept_governance_promotes_and_converts_candidate_relationships(tmp_path: Path) -> None:
    client = FakeNeo4jClient()
    store = _schema_store(tmp_path)
    engine = ClusterEngine(client=client, schema_store=store)

    proposed = engine.propose_concept_from_cluster(
        cluster_id="cluster-promote",
        parent_form="Form:Topic",
        particular_ids=["p-1", "p-2", "p-3"],
        algorithm="leiden",
    )

    governance = ConceptGovernance(client=client, schema_store=store)
    result = governance.promote_concept(proposed.concept_id, promoted_by="reviewer-1")

    assert result.status == "canonical"
    assert result.converted_relationships == 3
    assert result.provenance["promoted_by"] == "reviewer-1"
    assert client.concepts[proposed.concept_id]["status"] == "canonical"


def test_concept_governance_rejects_non_proposed_concepts(tmp_path: Path) -> None:
    client = FakeNeo4jClient()
    store = _schema_store(tmp_path)
    client.concepts["concept-1"] = {"status": "canonical"}

    governance = ConceptGovernance(client=client, schema_store=store)

    try:
        governance.promote_concept("concept-1")
    except ConceptPromotionError as exc:
        assert exc.code == "CONCEPT_NOT_PROPOSED"
    else:
        raise AssertionError("Expected ConceptPromotionError")


def test_concept_governance_merge_repoints_and_preserves_provenance(tmp_path: Path) -> None:
    client = FakeNeo4jClient()
    store = _schema_store(tmp_path)
    engine = ClusterEngine(client=client, schema_store=store)

    proposed = engine.propose_concept_from_cluster(
        cluster_id="cluster-merge",
        parent_form="Form:Topic",
        particular_ids=["p-1", "p-2"],
        algorithm="hdbscan",
    )
    client.concepts["concept-target"] = {"status": "canonical"}

    governance = ConceptGovernance(client=client, schema_store=store)
    result = governance.merge_proposed_concept(proposed.concept_id, "concept-target", merged_by="reviewer-2")

    assert result.status == "merged"
    assert result.repointed_relationships == 2
    assert result.provenance["target_concept_id"] == "concept-target"
    assert client.concepts[proposed.concept_id]["status"] == "merged"
    assert all(rel["concept_id"] == "concept-target" for rel in client.relationships)


def test_concept_governance_reject_marks_for_audit(tmp_path: Path) -> None:
    client = FakeNeo4jClient()
    store = _schema_store(tmp_path)
    engine = ClusterEngine(client=client, schema_store=store)
    proposed = engine.propose_concept_from_cluster(
        cluster_id="cluster-reject",
        parent_form="Form:Topic",
        particular_ids=["p-1"],
        algorithm="hdbscan",
    )

    governance = ConceptGovernance(client=client, schema_store=store)
    result = governance.reject_proposed_concept(proposed.concept_id, rejected_by="reviewer-3", reason="low_cohesion")

    assert result.status == "rejected"
    assert result.provenance["reason"] == "low_cohesion"
    assert client.concepts[proposed.concept_id]["status"] == "rejected"
