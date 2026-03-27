from __future__ import annotations

from pathlib import Path

import pytest

from logos.core import pipeline_executor
from logos.core.pipeline_executor import (
    PipelineContext,
    PipelineLoader,
    PipelineStageError,
    StageRegistry,
    run_pipeline,
)
from logos.models.bundles import InteractionMeta, RawInputBundle


class RecordingBus:
    def __init__(self) -> None:
        self.events = []

    def publish(self, event) -> None:
        self.events.append(event)


def _make_loader(tmp_path: Path, registry: StageRegistry, stages: list[str]) -> PipelineLoader:
    config_path = tmp_path / "pipelines.yml"
    stage_list = "\n".join(f"            - {stage}" for stage in stages)
    config_path.write_text(
        f"""
        example.pipeline:
          stages:
{stage_list}
        """,
        encoding="utf-8",
    )
    return PipelineLoader(registry, path=config_path)


def test_pipeline_emits_started_then_finished_events_in_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry = StageRegistry()

    @registry.register("stage.first")
    def _first(bundle: RawInputBundle, _ctx: PipelineContext) -> RawInputBundle:
        return RawInputBundle(meta=bundle.meta, raw_text=f"{bundle.text} done")

    loader = _make_loader(tmp_path, registry, ["stage.first"])
    bus = RecordingBus()
    monkeypatch.setattr(pipeline_executor.app_state, "EVENT_BUS", bus)

    bundle = RawInputBundle(meta=InteractionMeta(interaction_id="ix-123", interaction_type="test"), raw_text="hello")
    ctx = PipelineContext(context_data={"interaction_id": "ix-123"})

    run_pipeline("example.pipeline", bundle, ctx, loader=loader, registry=registry)

    event_types = [event.event_type for event in bus.events]
    assert event_types == ["logos.pipeline.stage_started", "logos.pipeline.stage_finished"]
    assert bus.events[0].correlation_id == "ix-123"
    assert bus.events[1].payload["status"] == "success"
    assert "duration_ms" in bus.events[1].payload


def test_pipeline_emits_stage_failed_event_when_stage_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry = StageRegistry()

    @registry.register("stage.crash")
    def _crash(_bundle: RawInputBundle, _ctx: PipelineContext) -> RawInputBundle:
        raise ValueError("boom")

    loader = _make_loader(tmp_path, registry, ["stage.crash"])
    bus = RecordingBus()
    monkeypatch.setattr(pipeline_executor.app_state, "EVENT_BUS", bus)

    bundle = RawInputBundle(meta=InteractionMeta(interaction_id="ix-456", interaction_type="test"), raw_text="hello")
    ctx = PipelineContext()

    with pytest.raises(PipelineStageError):
        run_pipeline("example.pipeline", bundle, ctx, loader=loader, registry=registry)

    event_types = [event.event_type for event in bus.events]
    assert event_types == ["logos.pipeline.stage_started", "logos.pipeline.stage_failed"]
    assert bus.events[1].payload["exception"]["type"] == "ValueError"
    assert bus.events[1].payload["exception"]["message"] == "boom"


def test_pipeline_event_publish_is_best_effort(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry = StageRegistry()

    @registry.register("stage.first")
    def _first(bundle: RawInputBundle, _ctx: PipelineContext) -> RawInputBundle:
        return bundle

    class FailingBus:
        def publish(self, _event) -> None:
            raise RuntimeError("bus unavailable")

    loader = _make_loader(tmp_path, registry, ["stage.first"])
    monkeypatch.setattr(pipeline_executor.app_state, "EVENT_BUS", FailingBus())

    bundle = RawInputBundle(meta=InteractionMeta(interaction_id="ix-789", interaction_type="test"), raw_text="hello")
    ctx = PipelineContext()

    result = run_pipeline("example.pipeline", bundle, ctx, loader=loader, registry=registry)
    assert result is bundle
