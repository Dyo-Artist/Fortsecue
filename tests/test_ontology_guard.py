from __future__ import annotations

from datetime import datetime, timezone

import pytest

import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from logos.core.ontology_guard import OntologyIntegrityError, OntologyIntegrityGuard
from logos.core.pipeline_executor import PipelineContext, stage_graph_upsert
from logos.graphio.schema_store import SchemaStore
from logos.graphio.upsert import GraphNode, GraphRelationship, InteractionBundle


def _store(tmp_path):
    node_path = tmp_path / "node_types.yml"
    rel_path = tmp_path / "relationship_types.yml"
    rules_path = tmp_path / "rules.yml"
    version_path = tmp_path / "version.yml"
    rules_path.write_text(
        """
usage_deprecation:
  min_usage: 1
  stale_after_days: 180
schema_conventions:
  concept_label: Concept
  instance_of_relationship: INSTANCE_OF
  particular_label: Particular
  form_concept_kind: Form
""".strip()
    )
    version_path.write_text("version: 1\nlast_updated: null\n")
    return SchemaStore(node_path, rel_path, rules_path, version_path)


def test_guard_rejects_orphan_particular(tmp_path):
    store = _store(tmp_path)
    guard = OntologyIntegrityGuard(schema_store=store)
    bundle = InteractionBundle(
        interaction=GraphNode(id="i1", label="Interaction", properties={}, source_uri="source://i1"),
        nodes=[GraphNode(id="p1", label="Particular", properties={"name": "fact"}, source_uri="source://i1")],
        relationships=[],
    )

    with pytest.raises(OntologyIntegrityError) as exc:
        guard.validate(bundle)

    error = exc.value
    codes = {item.code for item in error.violations}
    assert "PARTICULAR_MISSING_INSTANCE_OF" in codes
    assert "ORPHAN_PARTICULAR" in codes
    assert error.provenance["interaction_id"] == "i1"


def test_guard_rejects_invalid_concept_status(tmp_path):
    store = _store(tmp_path)
    guard = OntologyIntegrityGuard(schema_store=store)
    bundle = InteractionBundle(
        interaction=GraphNode(id="i2", label="Interaction", properties={}, source_uri="source://i2"),
        nodes=[
            GraphNode(
                id="c1",
                label="Concept",
                properties={"name": "BudgetTerm", "status": "draft"},
                source_uri="source://i2",
            )
        ],
        relationships=[],
    )

    with pytest.raises(OntologyIntegrityError) as exc:
        guard.validate(bundle)

    assert any(item.code == "INVALID_CONCEPT_STATUS" for item in exc.value.violations)


def test_graph_upsert_stage_runs_guard_before_upsert(monkeypatch, tmp_path):
    store = _store(tmp_path)
    bundle = InteractionBundle(
        interaction=GraphNode(id="i3", label="Interaction", properties={}, source_uri="source://i3"),
        nodes=[
            GraphNode(
                id="p3",
                label="Particular",
                properties={},
                concept_id="c3",
                concept_kind="Category",
                source_uri="source://i3",
            ),
            GraphNode(
                id="c3",
                label="Concept",
                properties={"name": "Category", "status": "proposed"},
                source_uri="source://i3",
            ),
        ],
        relationships=[
            GraphRelationship(
                src="p3",
                dst="c3",
                rel="INSTANCE_OF",
                src_label="Particular",
                dst_label="Concept",
                source_uri="source://i3",
            )
        ],
    )

    calls: list[str] = []

    def _build(_payload, _context):
        calls.append("build")
        return bundle

    def _upsert(_bundle, _context):
        calls.append("upsert")
        return {"status": "committed", "at": datetime.now(timezone.utc).isoformat()}

    monkeypatch.setattr("logos.core.pipeline_executor.legacy_stages.build_interaction_bundle_stage", _build)
    monkeypatch.setattr("logos.core.pipeline_executor.legacy_stages.upsert_interaction_bundle_stage", _upsert)

    ctx = PipelineContext(context_data={"schema_store": store})
    result = stage_graph_upsert({"interaction": {"id": "i3"}}, ctx)

    assert result["status"] == "committed"
    assert calls == ["build", "upsert"]


def test_graph_upsert_stage_blocks_automatic_form_creation(monkeypatch, tmp_path):
    store = _store(tmp_path)
    invalid_bundle = InteractionBundle(
        interaction=GraphNode(id="i4", label="Interaction", properties={}, source_uri="source://i4"),
        nodes=[
            GraphNode(
                id="p4",
                label="Particular",
                properties={"name": "X"},
                concept_id="form:stakeholder",
                concept_kind="Form",
                source_uri="source://i4",
            )
        ],
        relationships=[],
    )

    monkeypatch.setattr(
        "logos.core.pipeline_executor.legacy_stages.build_interaction_bundle_stage",
        lambda _payload, _context: invalid_bundle,
    )
    monkeypatch.setattr(
        "logos.core.pipeline_executor.legacy_stages.upsert_interaction_bundle_stage",
        lambda _bundle, _context: {"status": "should_not_happen"},
    )

    ctx = PipelineContext(context_data={"schema_store": store})
    with pytest.raises(OntologyIntegrityError) as exc:
        stage_graph_upsert({"interaction": {"id": "i4"}}, ctx)

    assert any(item.code == "AUTOMATIC_FORM_CREATION_FORBIDDEN" for item in exc.value.violations)
