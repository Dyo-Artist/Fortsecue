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


def test_apply_learning_signals_supports_sentiment_and_logging(tmp_path):
    base = tmp_path / "kb"
    store = KnowledgebaseStore(base_path=base, actor="tester")

    signals = {
        "lexicon_patterns": ["align with ESG"],
        "sentiment_overrides": [{"term": "blocker", "sentiment": -0.6, "context": "delivery"}],
        "schema_suggestions": {"node_types": [{"label": "Regulator", "description": "learned dynamically"}]},
        "flagged_terms": ["bespoke qualifier"],
    }

    updates = store.apply_learning_signals(signals)

    assert "align with ESG" in updates["lexicon_updates"]
    assert "blocker" in updates["sentiment_updates"]
    assert any(entry.get("label") == "Regulator" for entry in yaml.safe_load((base / "schema" / "node_types.yml").read_text())["node_types"])

    sentiment_path = base / "lexicons" / "sentiment_overrides.yml"
    sentiment_data = yaml.safe_load(sentiment_path.read_text())
    assert any(entry.get("term") == "blocker" for entry in sentiment_data["terms"])

    learning_log = yaml.safe_load((base / "learning" / "signals.yml").read_text())
    assert any(entry.get("type") == "flagged_terms" for entry in learning_log["signals"])


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


def test_sync_stage_applies_learning_signals(tmp_path):
    base = tmp_path / "kb"
    store = KnowledgebaseStore(base_path=base, actor="tester")

    bundle = ExtractionBundle(
        text="Follow up on the blocker",
        tokens=[],
        summary="",
        source_uri="memo-456",
        metadata={"learning_signals": {"sentiment_overrides": [{"term": "blocker", "sentiment": -0.4}]}},
        extraction={},
    )

    context: dict[str, object] = {
        "knowledge_updater": store,
        "learning_signals": {"lexicon_patterns": [{"lexicon": "obligation_phrases.yml", "regex": "follow up"}]},
    }

    sync_knowledgebase(bundle, context)

    updates = context["knowledgebase_updates"]
    assert "blocker" in updates["sentiment_updates"]
    assert updates["lexicon_updates"]

    sentiment_path = base / "lexicons" / "sentiment_overrides.yml"
    sentiment_data = yaml.safe_load(sentiment_path.read_text())
    assert any(entry.get("term") == "blocker" for entry in sentiment_data["terms"])

    learning_log = yaml.safe_load((base / "learning" / "signals.yml").read_text())
    assert learning_log["signals"]


def test_update_merge_thresholds_applies_delta(tmp_path):
    base = tmp_path / "kb"
    store = KnowledgebaseStore(base_path=base, actor="tester")

    rules_path = base / "rules" / "merge_thresholds.yml"
    rules_path.parent.mkdir(parents=True, exist_ok=True)
    rules_path.write_text(
        """metadata:
  version: "0.0.1"
  updated_at: "2024-01-01T00:00:00Z"
  updated_by: "system"

defaults:
  name_similarity: 0.8
  org_similarity: 0.9
""",
        encoding="utf-8",
    )

    applied = store.update_merge_thresholds({"name_similarity": 0.02}, scope="defaults", reason="test update")

    assert applied["name_similarity"] == 0.82

    data = yaml.safe_load(rules_path.read_text())
    assert data["defaults"]["name_similarity"] == 0.82
