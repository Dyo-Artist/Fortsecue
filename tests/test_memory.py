from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from logos.memory import MemoryManager, load_memory_rules
from logos.workflows import run_pipeline
from logos.workflows.bundles import ExtractionBundle
from logos.workflows.stages import build_preview_payload, capture_preview_memory, persist_session_memory


def test_memory_rules_are_loaded_from_knowledgebase():
    rules = load_memory_rules()
    assert "short_term" in rules
    assert rules["short_term"].get("default_ttl_seconds")
    assert rules["mid_term"].get("promotion_strength_threshold")


def test_memory_manager_promotes_and_persists_entries():
    manager = MemoryManager()
    short_item = manager.record_short_term("session-1", "reasoning_trace", ["step A"], importance=0.9)
    mid_item = manager.promote_short_term_to_mid_term("session-1", short_item.id, importance=0.9)
    assert mid_item is not None

    reinforced = manager.reinforce_mid_term(mid_item.id, amount=4.0, now=datetime.now(timezone.utc))
    assert reinforced is not None
    persisted: list[dict] = []

    report = manager.consolidate(
        session_id="session-1",
        now=datetime.now(timezone.utc) + timedelta(seconds=1),
        persist_fn=lambda item, payload: persisted.append(payload),
    )

    assert mid_item.id in report["persisted"]
    assert persisted[0]["key"] == "reasoning_trace"


def test_mid_term_items_expire_when_ttl_passed():
    manager = MemoryManager()
    item = manager.store_mid_term("temporary", "value", ttl_seconds=1)

    expired = manager.evict_expired(now=item.created_at + timedelta(seconds=2))

    assert item.id in expired


def test_build_preview_records_reasoning_in_short_term_memory():
    bundle = ExtractionBundle(
        text="Reasoning sample",
        tokens=["Reasoning", "sample"],
        summary="Reasoning sample",
        extraction={"reasoning": [{"source": "a", "target": "b", "relation": "result_of"}]},
    )
    context: dict[str, object] = {"interaction_id": "mem-1", "interaction_type": "note"}

    preview = build_preview_payload(bundle, context)

    assert preview["interaction"]["id"] == "mem-1"
    manager = context.get("memory_manager")
    assert isinstance(manager, MemoryManager)
    items = manager.get_short_term_items("mem-1")
    assert any(item.key == "reasoning_trace" for item in items)
    assert any(item.key == "preview_bundle" for item in items)


def test_memory_consolidation_pipeline_runs():
    manager = MemoryManager()
    mid_item = manager.store_mid_term("justification", "important detail", importance=1.0)
    manager.reinforce_mid_term(mid_item.id, amount=3.5)

    persisted: list[dict] = []
    context: dict[str, object] = {
        "interaction_id": "session-pipeline",
        "persist_long_term": lambda _item, payload: persisted.append(payload),
    }

    result = run_pipeline("memory_consolidation", manager, context)

    assert mid_item.id in result["persisted"]
    assert persisted and persisted[0]["key"] == "justification"


def test_session_memory_persists_to_knowledgebase(tmp_path: Path):
    preview = {
        "interaction": {"id": "sess-ctx", "summary": "sample", "type": "note"},
        "entities": {"concepts": ["alpha"]},
        "relationships": [],
    }
    context: dict[str, object] = {"interaction_id": "sess-ctx", "knowledgebase_path": tmp_path}

    capture_preview_memory(preview, context)
    persist_session_memory({"interaction_id": "sess-ctx"}, context)

    manager = context.get("memory_manager")
    assert isinstance(manager, MemoryManager)
    summaries = [item for item in manager.get_mid_term_items() if "session:sess-ctx" in item.key]
    assert summaries

    kb_file = tmp_path / "workflows" / "session_memory.yml"
    assert kb_file.exists()
    data = yaml.safe_load(kb_file.read_text())
    assert data["sessions"]
