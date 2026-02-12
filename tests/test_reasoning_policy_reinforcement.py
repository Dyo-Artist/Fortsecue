from __future__ import annotations

import json
from pathlib import Path

import yaml

from logos.knowledgebase.store import KnowledgebaseStore
from logos.reasoning.path_policy import load_or_train_and_persist_policy


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
                "materialised": {"path_length": 0.1},
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


def test_incremental_retraining_appends_reinforcement_log_and_archives_coefficients(tmp_path: Path):
    kb_root = tmp_path / "knowledgebase"
    policy_path = kb_root / "models" / "reasoning_path_policy.yml"
    _write_policy(policy_path, threshold=2)

    rows = [
        {
            "alert_id": "alert-1",
            "path_features": {"path_length": 3.0, "recency": 0.7},
            "model_score": 0.81,
            "outcome_label": "materialised",
            "timestamp": "2026-02-01T00:00:00+00:00",
        },
        {
            "alert_id": "alert-2",
            "path_features": {"path_length": 1.0, "recency": 0.2},
            "model_score": 0.12,
            "outcome_label": "false_positive",
            "timestamp": "2026-02-02T00:00:00+00:00",
        },
    ]

    calls: list[tuple[str, dict]] = []

    def fake_run_query(query: str, params):
        if "RETURN a.id AS alert_id" in query:
            return rows
        calls.append((query, dict(params)))
        return []

    store = KnowledgebaseStore(base_path=kb_root)
    trained = load_or_train_and_persist_policy(run_query=fake_run_query, kb_store=store)

    assert trained.version == "1.0.1"
    assert calls, "Expected policy persistence query to run"

    reinforcement_log = kb_root.parent / "data" / "reinforcement_log.jsonl"
    lines = [json.loads(line) for line in reinforcement_log.read_text().splitlines() if line.strip()]
    assert len(lines) == 2
    assert {line["outcome_label"] for line in lines} == {"materialised", "false_positive"}

    persisted = yaml.safe_load(policy_path.read_text())
    archive = persisted["reasoning_policy"].get("coefficient_archive")
    assert isinstance(archive, list)
    assert archive[-1]["version"] == "1.0.0"


def test_incremental_retraining_not_triggered_when_new_samples_below_threshold(tmp_path: Path):
    kb_root = tmp_path / "knowledgebase"
    policy_path = kb_root / "models" / "reasoning_path_policy.yml"
    _write_policy(policy_path, threshold=3)

    rows = [
        {
            "alert_id": "alert-1",
            "path_features": {"path_length": 3.0},
            "model_score": 0.61,
            "outcome_label": "acknowledged",
            "timestamp": "2026-02-01T00:00:00+00:00",
        }
    ]

    def fake_run_query(query: str, params):
        if "RETURN a.id AS alert_id" in query:
            return rows
        raise AssertionError("Training persistence query should not run")

    store = KnowledgebaseStore(base_path=kb_root)
    loaded = load_or_train_and_persist_policy(run_query=fake_run_query, kb_store=store)

    assert loaded.version == "1.0.0"
