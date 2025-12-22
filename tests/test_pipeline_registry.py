from __future__ import annotations

from pathlib import Path

import pytest

from logos.core.pipeline_executor import (
    DEFAULT_PIPELINE_PATH,
    PipelineConfigError,
    PipelineContext,
    PipelineLoader,
    StageRegistry,
    STAGE_REGISTRY,
    run_pipeline,
)
from logos.models.bundles import InteractionMeta, RawInputBundle


def test_pipeline_loader_reads_yaml_registry():
    loader = PipelineLoader(STAGE_REGISTRY, path=DEFAULT_PIPELINE_PATH)
    pipelines = loader.load()

    assert "pipeline.interaction_ingest" in pipelines
    assert pipelines["pipeline.interaction_ingest"] == [
        "ingest.validate_input",
        "ingest.parse_or_transcribe",
        "nlp.extract",
        "normalise.resolve_entities",
        "preview.assemble",
    ]
    assert pipelines["pipeline.interaction_commit"] == [
        "commit.validate",
        "graph.upsert",
        "alerts.evaluate",
        "learn.capture_feedback",
    ]


def test_run_pipeline_executes_stages_in_order(tmp_path: Path):
    registry = StageRegistry()

    @registry.register("stage.first")
    def _first(bundle: RawInputBundle, ctx: PipelineContext) -> RawInputBundle:
        ctx.to_mapping().setdefault("trace", []).append("stage.first")
        new_meta = InteractionMeta(
            interaction_id=bundle.meta.interaction_id,
            interaction_type=bundle.meta.interaction_type,
        )
        return RawInputBundle(meta=new_meta, raw_text=f"{bundle.text} processed")

    @registry.register("stage.second")
    def _second(bundle: RawInputBundle, ctx: PipelineContext) -> RawInputBundle:
        ctx.to_mapping().setdefault("trace", []).append("stage.second")
        return RawInputBundle(meta=bundle.meta, raw_text=f"{bundle.text} twice")

    config_path = tmp_path / "pipelines.yml"
    config_path.write_text(
        """
        example.pipeline:
          stages:
            - stage.first
            - stage.second
        """,
        encoding="utf-8",
    )

    loader = PipelineLoader(registry, path=config_path)
    ctx = PipelineContext(request_id="req-1", context_data={"trace": []})
    base_meta = InteractionMeta(interaction_id="abc123", interaction_type="test")
    bundle = RawInputBundle(meta=base_meta, raw_text="hello")

    result = run_pipeline("example.pipeline", bundle, ctx, loader=loader, registry=registry)

    assert isinstance(result, RawInputBundle)
    assert result.text == "hello processed twice"
    assert ctx.context_data["trace"] == ["stage.first", "stage.second"]


def test_pipeline_loader_errors_on_unknown_stage(tmp_path: Path):
    registry = StageRegistry()
    config_path = tmp_path / "pipelines.yml"
    config_path.write_text(
        """
        bad.pipeline:
          stages:
            - missing.stage
        """,
        encoding="utf-8",
    )

    loader = PipelineLoader(registry, path=config_path)
    with pytest.raises(PipelineConfigError):
        loader.load()


def test_pipeline_preserves_meta_and_versions(tmp_path: Path):
    registry = StageRegistry()

    @registry.register("stage.override")
    def _override(bundle: RawInputBundle, ctx: PipelineContext) -> RawInputBundle:
        ctx.to_mapping()["seen"] = bundle.meta.interaction_id
        # Intentionally change the interaction id and versions to ensure propagation resets them.
        altered_meta = InteractionMeta(interaction_id="different", interaction_type=bundle.meta.interaction_type)
        new_bundle = RawInputBundle(meta=altered_meta, raw_text=bundle.text)
        new_bundle.bundle_version = "0.0"
        new_bundle.processing_version = "0.0"
        return new_bundle

    config_path = tmp_path / "pipelines.yml"
    config_path.write_text(
        """
        example.pipeline:
          stages:
            - stage.override
        """,
        encoding="utf-8",
    )

    loader = PipelineLoader(registry, path=config_path)
    ctx = PipelineContext()
    base_meta = InteractionMeta(interaction_id="persist-me", interaction_type="demo")
    bundle = RawInputBundle(meta=base_meta, raw_text="payload")
    bundle.bundle_version = "9.9"
    bundle.processing_version = "8.8"

    result = run_pipeline("example.pipeline", bundle, ctx, loader=loader, registry=registry)

    assert result.meta.interaction_id == "persist-me"
    assert result.bundle_version == "9.9"
    assert result.processing_version == "8.8"
    assert ctx.context_data["seen"] == "persist-me"
