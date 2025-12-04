from datetime import datetime, timezone

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from logos.agents.assistant import (
    explain_risk_for_user,
    record_agent_assist,
    summarise_interaction_for_user,
)
from logos.graphio import upsert
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


def test_upsert_agent_assist_links_agent_and_user():
    tx = FakeTx()
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    agent = upsert.AgentModel(id="agent_alpha", name="Alpha", role="assistant", source_uri="src", created_by="tester")
    user = upsert.PersonModel(id="user_1", name="User One", source_uri="src")

    upsert.upsert_agent_assist(tx, agent, user, now)

    cypher, params = tx.calls[0]
    assert "MERGE (a:Agent" in cypher
    assert "ASSISTS" in cypher
    assert params["agent_id"] == "agent_alpha"
    assert params["user_id"] == "user_1"
    assert params["now"] == now.isoformat()


def test_record_agent_assist_runs_transaction():
    client = FakeClient()
    now = datetime(2024, 2, 1, tzinfo=timezone.utc)

    record_agent_assist(
        "user_2",
        "User Two",
        agent_id="agent_beta",
        agent_name="Beta",
        client_factory=lambda: client,
        now=now,
    )

    assert client.tx is not None
    cypher, params = client.tx.calls[0]
    assert params["agent_id"] == "agent_beta"
    assert params["user_name"] == "User Two"


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
    )

    assert result["summary"].startswith("One two three")
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
