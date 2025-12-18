import yaml

from logos.knowledgebase.store import KnowledgebaseStore
from logos.workflows.bundles import ExtractionBundle
from logos.workflows.stages import sync_knowledgebase


def test_add_obligation_phrase_tracks_version_and_changelog(tmp_path):
    base = tmp_path / "kb"
    store = KnowledgebaseStore(base_path=base, actor="tester")

    lexicon_path = base / "lexicons" / "obligation_phrases.yml"
    lexicon_path.parent.mkdir(parents=True, exist_ok=True)
    lexicon_path.write_text("patterns: []\n", encoding="utf-8")

    added = store.add_obligation_phrase("deliver the new module", reason="learned from test")

    assert added is True

    data = yaml.safe_load(lexicon_path.read_text())
    assert data["metadata"]["version"] == "0.0.1"
    assert any(entry.get("regex") for entry in data["patterns"])

    changelog = yaml.safe_load((base / "versioning" / "changelog.yml").read_text())
    assert changelog[-1]["path"] == "lexicons/obligation_phrases.yml"


def test_schema_updates_increment_version(tmp_path):
    base = tmp_path / "kb"
    store = KnowledgebaseStore(base_path=base, actor="tester")

    added = store.add_node_type({"label": "CustomNode", "description": "runtime addition"}, reason="schema learning")

    assert added is True

    schema_path = base / "schema" / "node_types.yml"
    data = yaml.safe_load(schema_path.read_text())
    assert data["metadata"]["version"] == "0.0.1"
    assert data["node_types"][0]["label"] == "CustomNode"


def test_sync_stage_writes_through_updater(tmp_path):
    base = tmp_path / "kb"
    store = KnowledgebaseStore(base_path=base, actor="tester")

    bundle = ExtractionBundle(
        text="Report submission",
        tokens=[],
        summary="",
        source_uri="memo-123",
        metadata={},
        extraction={"entities": {"commitments": ["submit the report by Friday"]}},
    )

    context: dict[str, object] = {"knowledge_updater": store}
    result = sync_knowledgebase(bundle, context)

    assert result is bundle
    assert context["knowledgebase_updates"]["lexicon_updates"] == ["submit the report by Friday"]

    lexicon_path = base / "lexicons" / "obligation_phrases.yml"
    data = yaml.safe_load(lexicon_path.read_text())
    assert any(entry.get("regex") for entry in data["patterns"])
