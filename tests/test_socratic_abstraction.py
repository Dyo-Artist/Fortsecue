from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from logos.core.ontology_guard import OntologyIntegrityError, OntologyIntegrityGuard
from logos.graphio.schema_store import SchemaStore
from logos.graphio.upsert import GraphNode, GraphRelationship, InteractionBundle
from logos.knowledgebase.store import KnowledgebaseStore
from logos.learning.clustering.cluster_engine import ClusterEngine
from logos.learning.clustering.concept_governance import ConceptGovernance
from logos.learning.embeddings.concept_assignment import ConceptAssignmentEngine, ConceptAssignmentSettings
from logos.reasoning.path_policy import evaluate_policy, load_or_train_and_persist_policy


def _cosine(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(a * a for a in left)) or 1.0
    right_norm = math.sqrt(sum(b * b for b in right)) or 1.0
    return numerator / (left_norm * right_norm)


class FakeNeo4jClient:
    def __init__(self) -> None:
        self.concepts: dict[str, dict] = {}
        self.relationships: list[dict] = []

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
            return []
        raise AssertionError(f"Unexpected query: {cypher}")


def _schema_store(tmp_path: Path, *, mutable: bool = True) -> SchemaStore:
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
        "usage_deprecation:\n"
        "  min_usage: 1\n"
        "  stale_after_days: 180\n"
        "schema_conventions:\n"
        "  concept_label: Concept\n"
        "  particular_label: Particular\n"
        "  candidate_instance_of_relationship: CANDIDATE_INSTANCE_OF\n"
        "  instance_of_relationship: INSTANCE_OF\n"
        "  form_concept_kind: Form\n"
    )
    version.write_text("version: 1\nlast_updated: null\n")
    return SchemaStore(node_types, rel_types, rules, version, mutable=mutable)


def _write_policy(path: Path, *, threshold: int) -> None:
    payload = {
        "reasoning_policy": {
            "id": "reasoning_path_scoring",
            "version": "1.0.0",
            "trained_at": "2026-01-01T00:00:00+00:00",
            "outcomes": ["acknowledged", "materialised", "false_positive"],
            "intercepts": {"acknowledged": 0.0, "materialised": 0.2, "false_positive": 0.0},
            "coefficients": {
                "acknowledged": {"path_length": 0.0},
                "materialised": {"path_length": 0.4, "recency": 0.3},
                "false_positive": {"path_length": -0.1},
            },
            "retraining": {
                "incremental_threshold": threshold,
                "reinforcement_log": "data/reinforcement_log.jsonl",
                "max_archive_entries": 5,
            },
            "coefficient_archive": [],
        }
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False))


def test_pink_cow_variation_prefers_cow_concept() -> None:
    engine = ConceptAssignmentEngine(ConceptAssignmentSettings(embedding_similarity_threshold=0.05, decision_threshold=0.2))

    cow_embedding = engine._embed_text("cow")
    pig_embedding = engine._embed_text("pig")
    pink_cow_embedding = engine._embed_text("pink spotted cow")

    assert _cosine(pink_cow_embedding, cow_embedding) > _cosine(pink_cow_embedding, pig_embedding)


def test_new_synonym_cluster_creates_proposed_concept(tmp_path: Path) -> None:
    client = FakeNeo4jClient()
    store = _schema_store(tmp_path)
    engine = ClusterEngine(client=client, schema_store=store)

    synonym_terms = ["budget overrun", "cost overrun", "spend overrun", "budget overrun"]
    proposal = engine.propose_concept_from_cluster(
        cluster_id="cluster-synonyms-1",
        parent_form="Form:Issue",
        particular_ids=synonym_terms,
        algorithm="hdbscan",
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        provenance={"source": "synonym-cluster-test"},
    )

    assert proposal.status == "proposed"
    assert proposal.provenance["review_required"] is True
    assert len(client.relationships) == 3


def test_path_reinforcement_learning_downranks_after_false_positives(tmp_path: Path) -> None:
    kb_root = tmp_path / "knowledgebase"
    policy_path = kb_root / "models" / "reasoning_path_policy.yml"
    _write_policy(policy_path, threshold=1)

    sample_features = {"path_length": 2.0, "recency": 0.7}

    def no_rows(query: str, params):
        if "RETURN a.id AS alert_id" in query:
            return []
        return []

    baseline = load_or_train_and_persist_policy(run_query=no_rows, kb_store=KnowledgebaseStore(base_path=kb_root))
    baseline_score, _, _ = evaluate_policy(baseline, sample_features)

    rows = [
        {
            "alert_id": "alert-fp-1",
            "path_features": {"path_length": 2.1, "recency": 0.72},
            "model_score": 0.82,
            "outcome_label": "false_positive",
            "timestamp": "2026-02-01T00:00:00+00:00",
        },
        {
            "alert_id": "alert-fp-2",
            "path_features": {"path_length": 1.9, "recency": 0.69},
            "model_score": 0.78,
            "outcome_label": "false_positive",
            "timestamp": "2026-02-02T00:00:00+00:00",
        },
        {
            "alert_id": "alert-fp-3",
            "path_features": {"path_length": 2.0, "recency": 0.7},
            "model_score": 0.80,
            "outcome_label": "false_positive",
            "timestamp": "2026-02-03T00:00:00+00:00",
        },
    ]

    def false_positive_rows(query: str, params):
        if "RETURN a.id AS alert_id" in query:
            return rows
        return []

    reinforced = load_or_train_and_persist_policy(
        run_query=false_positive_rows,
        kb_store=KnowledgebaseStore(base_path=kb_root),
    )
    reinforced_score, _, _ = evaluate_policy(reinforced, sample_features)

    assert reinforced.version == "1.0.1"
    assert reinforced_score < baseline_score


def test_concept_promotion_workflow_transitions_proposed_to_canonical(tmp_path: Path) -> None:
    client = FakeNeo4jClient()
    store = _schema_store(tmp_path)
    engine = ClusterEngine(client=client, schema_store=store)

    proposed = engine.propose_concept_from_cluster(
        cluster_id="cluster-promote-1",
        parent_form="Form:Topic",
        particular_ids=["p-1", "p-2"],
        algorithm="leiden",
    )

    governance = ConceptGovernance(client=client, schema_store=store)
    result = governance.promote_concept(proposed.concept_id, promoted_by="reviewer")

    assert result.status == "canonical"
    assert result.converted_relationships == 2
    assert client.concepts[proposed.concept_id]["status"] == "canonical"


def test_orphan_prevention_ontology_guard_blocks_orphan_particular(tmp_path: Path) -> None:
    store = _schema_store(tmp_path, mutable=False)
    guard = OntologyIntegrityGuard(schema_store=store)
    bundle = InteractionBundle(
        interaction=GraphNode(id="i-orphan", label="Interaction", properties={}, source_uri="source://i-orphan"),
        nodes=[GraphNode(id="p-orphan", label="Particular", properties={"name": "orphan"}, source_uri="source://i-orphan")],
        relationships=[
            GraphRelationship(
                src="p-orphan",
                dst="c-other",
                rel="RELATES_TO",
                src_label="Particular",
                dst_label="Concept",
                source_uri="source://i-orphan",
            )
        ],
    )

    with pytest.raises(OntologyIntegrityError) as exc:
        guard.validate(bundle)

    assert any(item.code == "ORPHAN_PARTICULAR" for item in exc.value.violations)
