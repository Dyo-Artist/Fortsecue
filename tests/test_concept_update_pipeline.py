from __future__ import annotations

from pathlib import Path

import yaml

from logos.core.pipeline_executor import PipelineContext
from logos.graphio.schema_store import SchemaStore
from logos.pipelines.concept_update import stage_concept_update


class FakeTx:
    def __init__(self, calls: list[tuple[str, dict]]) -> None:
        self.calls = calls

    def run(self, cypher: str, params: dict | None = None) -> None:
        self.calls.append((cypher, params or {}))


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def run_in_tx(self, fn) -> None:
        tx = FakeTx(self.calls)
        fn(tx)


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _schema_store(tmp_path: Path) -> SchemaStore:
    return SchemaStore(
        node_types_path=tmp_path / "schema/node_types.yml",
        relationship_types_path=tmp_path / "schema/relationship_types.yml",
        rules_path=tmp_path / "schema/rules.yml",
        version_path=tmp_path / "versioning/schema.yml",
        mutable=False,
    )


def test_concept_update_stage_upserts_nodes_and_relationships(tmp_path: Path) -> None:
    concepts_dir = tmp_path / "concepts"
    _write_yaml(
        concepts_dir / "forms.yml",
        {
            "metadata": {"version": "0.1.0"},
            "forms": [{"id": "form_stakeholder", "name": "Stakeholder"}],
        },
    )
    _write_yaml(
        concepts_dir / "stakeholder_types.yml",
        {
            "metadata": {"version": "0.1.0"},
            "stakeholder_types": [
                {"id": "st_regulator", "name": "Regulator", "form_id": "form_stakeholder"}
            ],
        },
    )

    fake_client = FakeClient()
    ctx = PipelineContext(
        context_data={
            "knowledgebase_path": tmp_path,
            "graph_client_factory": lambda: fake_client,
            "schema_store": _schema_store(tmp_path),
            "rebuild_hierarchy": True,
        }
    )

    result = stage_concept_update({}, ctx)

    assert result["concept_count"] == 2
    assert result["relationship_count"] == 1

    cypher_texts = [call[0] for call in fake_client.calls]
    assert any("MERGE (n:Concept" in cypher for cypher in cypher_texts)
    assert any("PARENT_OF" in cypher for cypher in cypher_texts)
    assert any("DELETE r" in cypher for cypher in cypher_texts)
