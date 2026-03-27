from __future__ import annotations

from pathlib import Path

import yaml

from logos.core.pipeline_executor import PipelineContext
from logos.pipelines.interaction_commit import stage_reflect_and_learn


def _seed_minimal_kb(base_path: Path) -> None:
    rules_path = base_path / "rules" / "merge_thresholds.yml"
    rules_path.parent.mkdir(parents=True, exist_ok=True)
    rules_path.write_text(
        """metadata:
  version: "0.0.1"
defaults:
  name_similarity: 0.8
  org_similarity: 0.9
""",
        encoding="utf-8",
    )


def test_learning_hook_defaults_to_env_kb_path(monkeypatch, tmp_path: Path) -> None:
    kb_path = tmp_path / "kb"
    _seed_minimal_kb(kb_path)
    monkeypatch.setenv("LOGOS_KB_DIR", str(kb_path))

    feedback_bundle = {
        "meta": {
            "interaction_id": "i-1",
            "interaction_type": "note",
            "source_type": "text",
            "created_by": "tester",
        },
        "feedback": "user_corrections",
        "processing_version": "0.1",
        "corrections": [
            {
                "path": "commitments[0].due_date",
                "before": "2024-09-01",
                "after": "by Sept 1",
            }
        ],
        "user_id": "tester",
        "timestamp": "2026-03-27T00:00:00+00:00",
    }

    ctx = PipelineContext(
        user_id="tester",
        context_data={
            "feedback_bundle": feedback_bundle,
            "feedback_recurring_threshold": 1,
        },
    )

    stage_reflect_and_learn({"status": "ok"}, ctx)

    obligation_path = kb_path / "lexicons" / "obligation_phrases.yml"
    data = yaml.safe_load(obligation_path.read_text(encoding="utf-8"))
    assert any("Sept\\ 1" in str(entry.get("regex")) for entry in data["patterns"])


def test_learning_hook_soft_skip_when_kb_explicitly_disabled(tmp_path: Path) -> None:
    feedback_bundle = {
        "meta": {
            "interaction_id": "i-2",
            "interaction_type": "note",
            "source_type": "text",
            "created_by": "tester",
        },
        "feedback": "user_corrections",
        "processing_version": "0.1",
        "corrections": [{"path": "summary", "before": "a", "after": "b"}],
        "user_id": "tester",
        "timestamp": "2026-03-27T00:00:00+00:00",
    }

    ctx = PipelineContext(
        user_id="tester",
        context_data={
            "knowledgebase_path": None,
            "feedback_bundle": feedback_bundle,
            "feedback_recurring_threshold": 1,
        },
    )

    result = stage_reflect_and_learn({"status": "ok"}, ctx)
    assert result == {"status": "ok"}
    assert not (tmp_path / "lexicons" / "obligation_phrases.yml").exists()
