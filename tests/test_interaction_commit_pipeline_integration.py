from __future__ import annotations

from pathlib import Path

import yaml

from logos.core.pipeline_executor import PipelineContext, PipelineLoader, STAGE_REGISTRY, run_pipeline
from logos.models.bundles import FeedbackBundle, InteractionMeta


def test_reflect_stage_runs_post_commit_with_feedback_bundle(tmp_path: Path) -> None:
    @STAGE_REGISTRY.register("test.commit.marker")
    def _commit_marker(bundle: dict[str, object], ctx: PipelineContext) -> dict[str, object]:
        context = ctx.to_mapping()
        context.setdefault("trace", []).append("test.commit.marker")
        context["commit_completed"] = True
        return bundle

    config_path = tmp_path / "pipelines.yml"
    config_path.write_text(
        """
        audit.commit.pipeline:
          stages:
            - test.commit.marker
            - learn.capture_feedback
            - S7_REFLECT_AND_LEARN
        """,
        encoding="utf-8",
    )

    kb_path = tmp_path / "kb"
    rules_path = kb_path / "rules" / "merge_thresholds.yml"
    rules_path.parent.mkdir(parents=True, exist_ok=True)
    rules_path.write_text(
        """metadata:
  version: \"0.0.1\"
  updated_at: \"2024-01-01T00:00:00Z\"
  updated_by: \"system\"

defaults:
  name_similarity: 0.8
""",
        encoding="utf-8",
    )

    feedback_bundle = FeedbackBundle(
        meta=InteractionMeta(interaction_id="ix-123", interaction_type="note"),
        feedback="user_corrections",
        user_id="tester",
        corrections=[
            {"path": "commitments[0].due_date", "before": "tomorrow", "after": "by Friday"},
            {"path": "entities[0].confidence", "before": 0.9, "after": 0.7},
        ],
    )

    context = PipelineContext(
        request_id="ix-123",
        user_id="tester",
        context_data={
            "interaction_id": "ix-123",
            "knowledgebase_path": kb_path,
            "feedback_dir": tmp_path / "feedback",
            "feedback_bundle": feedback_bundle,
            "feedback_recent_limit": 10,
            "feedback_recurring_threshold": 1,
            "trace": [],
        },
    )

    loader = PipelineLoader(STAGE_REGISTRY, path=config_path)
    run_pipeline("audit.commit.pipeline", {"interaction_id": "ix-123"}, context, loader=loader)

    trace = context.context_data["trace"]
    assert trace.index("test.commit.marker") < trace.index("S7_REFLECT_AND_LEARN")
    assert context.context_data["commit_completed"] is True

    feedback_path = tmp_path / "feedback" / "feedback.jsonl"
    assert feedback_path.exists()
    assert "by Friday" in feedback_path.read_text(encoding="utf-8")

    lexicon_path = kb_path / "lexicons" / "obligation_phrases.yml"
    lexicon_data = yaml.safe_load(lexicon_path.read_text(encoding="utf-8"))
    assert any("friday" in str(pattern.get("regex", "")).lower() for pattern in lexicon_data["patterns"])

    thresholds_data = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
    assert thresholds_data["defaults"]["name_similarity"] != 0.8
