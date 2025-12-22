from datetime import datetime, timezone

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from logos.agents.assistant import (
    AgentContextBuffer,
    explain_risk_for_user,
    record_agent_assist,
    summarise_interaction_for_user,
)
from logos.graphio.schema_store import SchemaStore
from logos.model_tiers import ModelConfigError, ModelSelection


class FakeTx:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def run(self, cypher: str, params: dict | None = None):
        self.calls.append((cypher, params or {}))
        return []


class FakeClient:
    def __init__(self) -> None:
        self.tx: FakeTx | None = None

    def run_in_tx(self, fn):
        self.tx = FakeTx()
        fn(self.tx)


def test_record_agent_assist_runs_transaction(tmp_path):
    client = FakeClient()
    now = datetime(2024, 2, 1, tzinfo=timezone.utc)
    store = SchemaStore(
        tmp_path / "node_types.yml",
        tmp_path / "relationship_types.yml",
        tmp_path / "rules.yml",
        tmp_path / "version.yml",
    )

    record_agent_assist(
        "user_2",
        "User Two",
        agent_id="agent_beta",
        agent_name="Beta",
        client_factory=lambda: client,
        now=now,
        schema_store=store,
    )

    assert client.tx is not None
    cyphers = [call[0] for call in client.tx.calls]
    assert any("Agent" in stmt for stmt in cyphers)
    assert any("ASSISTS" in stmt for stmt in cyphers)
    assert any("Person" in stmt for stmt in cyphers)


def test_summarise_interaction_records_assist_and_returns_summary():
    calls: list[dict] = []

    def _record(user_id: str, user_name: str | None = None, **kwargs) -> None:
        calls.append({"user_id": user_id, "user_name": user_name, **kwargs})

    selection = ModelSelection(task="summary_interaction", tier="rule_only", name="rule_engine", parameters={})

    result = summarise_interaction_for_user(
        "One two three four five six.",
        "user_3",
        user_name="User Three",
        model_selector=lambda task: selection,
        record_assist_fn=_record,
        memory_rules={"agent_context": {"fallback_summary_max_words": 3}},
    )

    assert len(result["summary"].split()) <= 3
    assert result["tier"] == "rule_only"
    assert calls[0]["user_id"] == "user_3"


def test_explain_risk_falls_back_on_model_error():
    calls: list[dict] = []

    def _record(user_id: str, user_name: str | None = None, **kwargs) -> None:
        calls.append({"user_id": user_id, **kwargs})

    def _raise_missing(task: str):
        raise ModelConfigError("missing config")

    result = explain_risk_for_user(
        "Schedule delay from supplier onboarding.",
        "user_4",
        record_assist_fn=_record,
        model_selector=_raise_missing,
    )

    assert "Schedule delay" in result["explanation"]
    assert result["tier"] == "rule_only"
    assert calls[0]["agent_id"] == "agent_logos"


def test_context_buffer_stores_recent_turns():
    buffer = AgentContextBuffer(memory_rules={"agent_context": {"context_turn_limit": 2}})

    buffer.add_turn("user_a", "Hello?", "Hi there", metadata={"channel": "ui"})
    buffer.add_turn("user_b", "Status?", "All green")
    buffer.add_turn("user_a", "Reminder", "Noted")

    recent_all = buffer.recent()
    assert len(recent_all) == 2
    assert recent_all[-1]["query"] == "Reminder"

    recent_user_a = buffer.recent(user_id="user_a")
    assert all(turn["user_id"] == "user_a" for turn in recent_user_a)
    assert recent_user_a[-1]["response"] == "Noted"


def test_summarise_updates_context_buffer():
    buffer = AgentContextBuffer(memory_rules={"agent_context": {"context_turn_limit": 5}})

    selection = ModelSelection(task="summary_interaction", tier="rule_only", name="rule_engine", parameters={})

    summarise_interaction_for_user(
        "One two three four five six seven eight nine ten.",
        "user_context",
        model_selector=lambda task: selection,
        record_assist_fn=lambda *args, **kwargs: None,
        context_buffer=buffer,
    )

    stored = buffer.recent(user_id="user_context")
    assert stored
    assert stored[-1]["metadata"]["task"] == "summary_interaction"
