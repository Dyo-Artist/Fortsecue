from __future__ import annotations

import json
from pathlib import Path

import yaml

from logos.core.pipeline_executor import PipelineContext
from logos.pipelines.interaction_commit import stage_reflect_and_learn


def _write_feedback(path: Path, entries: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry) + "\n")


def test_reflect_and_learn_updates_knowledgebase(tmp_path: Path) -> None:
    kb_path = tmp_path / "kb"
    feedback_dir = tmp_path / "feedback"

    rules_path = kb_path / "rules" / "merge_thresholds.yml"
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

    feedback_entries = [
        {
            "corrections": [
                {"path": "commitments[0].due_date", "before": "2024-09-01", "after": "by Sept 1"},
                {"path": "summary", "before": "deliver report", "after": "deliver final report"},
                {"path": "entities[0].confidence", "before": 0.82, "after": 0.75},
                {"path": "entities[0].concept", "before": "risk", "after": "delivery risk"},
                {"path": "misc", "before": "alpha", "after": None},
            ]
        },
        {
            "corrections": [
                {"path": "commitments[0].due_date", "before": "2024-09-01", "after": "by Sept 1"},
                {"path": "summary", "before": "deliver report", "after": "deliver final report"},
                {"path": "entities[0].confidence", "before": 0.78, "after": 0.7},
            ]
        },
    ]

    feedback_path = feedback_dir / "feedback.jsonl"
    _write_feedback(feedback_path, feedback_entries)

    ctx = PipelineContext(
        user_id="tester",
        context_data={
            "knowledgebase_path": kb_path,
            "feedback_dir": feedback_dir,
            "feedback_recent_limit": 10,
            "feedback_recurring_threshold": 2,
        },
    )

    stage_reflect_and_learn({"status": "ok"}, ctx)

    lexicon_path = kb_path / "lexicons" / "obligation_phrases.yml"
    lexicon_data = yaml.safe_load(lexicon_path.read_text())
    assert any(entry.get("regex") for entry in lexicon_data["patterns"])

    synonyms_path = kb_path / "lexicons" / "synonyms.yml"
    synonyms_data = yaml.safe_load(synonyms_path.read_text())
    assert any(entry.get("from") == "deliver report" for entry in synonyms_data["pairs"])

    thresholds_data = yaml.safe_load(rules_path.read_text())
    assert thresholds_data["defaults"]["name_similarity"] != 0.8

    signals_path = kb_path / "learning" / "signals.yml"
    signals_data = yaml.safe_load(signals_path.read_text())
    assert any(signal.get("type") == "concept_promotion_candidate" for signal in signals_data["signals"])
    assert any(signal.get("type") == "feedback_review" for signal in signals_data["signals"])
