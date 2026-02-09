from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Sequence

import yaml
from pydantic import BaseModel

from logos.ingest import doc_ingest, note_ingest
from logos.interfaces.local_asr_stub import TranscriptionFailure
from logos.models.bundles import (
    ExtractionBundle,
    InteractionMeta,
    PipelineBundle,
    PreviewBundle,
    RawInputBundle,
)
from logos.staging.store import StagingStore
from logos.workflows import stages as legacy_stages

DEFAULT_PIPELINE_PATH = Path(__file__).resolve().parent.parent / "knowledgebase" / "pipelines.yml"


class PipelineConfigError(RuntimeError):
    """Raised when the pipeline configuration is missing or malformed."""


class PipelineStageError(RuntimeError):
    """Raised when a pipeline stage fails during execution."""

    def __init__(self, stage_id: str, cause: Exception):
        super().__init__(f"Stage '{stage_id}' failed: {cause}")
        self.stage_id = stage_id
        self.cause = cause


class StageRegistry:
    """Registry of callable pipeline stages keyed by stage id."""

    def __init__(self) -> None:
        self._stages: Dict[str, Callable[[Any, "PipelineContext"], Any]] = {}

    def register(self, stage_id: str, fn: Callable[[Any, "PipelineContext"], Any] | None = None):
        def _decorator(func: Callable[[Any, "PipelineContext"], Any]):
            self._stages[stage_id] = func
            return func

        if fn is None:
            return _decorator

        return _decorator(fn)

    def get(self, stage_id: str) -> Callable[[Any, "PipelineContext"], Any]:
        try:
            return self._stages[stage_id]
        except KeyError as exc:  # pragma: no cover - defensive guard
            raise PipelineConfigError(f"Stage '{stage_id}' is not registered") from exc

    def validate_stages(self, stage_ids: Iterable[str]) -> None:
        missing = [stage_id for stage_id in stage_ids if stage_id not in self._stages]
        if missing:
            raise PipelineConfigError(f"Stages not registered: {', '.join(missing)}")

    def list_stage_ids(self) -> List[str]:
        return list(self._stages)


@dataclass
class PipelineContext:
    """Runtime context shared across pipeline stages."""

    request_id: str | None = None
    user_id: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    context_data: Dict[str, Any] = field(default_factory=dict)
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("logos.pipeline"))

    def to_mapping(self) -> Dict[str, Any]:
        """Expose a mutable mapping for legacy stage helpers."""

        if self.request_id is not None:
            self.context_data.setdefault("request_id", self.request_id)
        if self.user_id is not None:
            self.context_data.setdefault("user", self.user_id)
        self.context_data.setdefault("started_at", self.started_at)
        return self.context_data


class PipelineLoader:
    """Load declarative pipeline definitions from YAML."""

    def __init__(self, registry: StageRegistry, path: Path | None = None) -> None:
        self.registry = registry
        self.path = path or DEFAULT_PIPELINE_PATH

    def load(self) -> Dict[str, List[str]]:
        if not self.path.exists():
            raise PipelineConfigError(f"Pipeline registry missing at {self.path}")

        try:
            raw = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:  # pragma: no cover - defensive guard
            raise PipelineConfigError("Failed to parse pipeline registry YAML") from exc

        if not isinstance(raw, Mapping):
            raise PipelineConfigError("Pipeline registry must be a mapping")

        pipelines: Dict[str, List[str]] = {}
        for pipeline_id, config in raw.items():
            if pipeline_id == "metadata":
                continue

            stages = self._extract_stages(config)
            self.registry.validate_stages(stages)
            pipelines[pipeline_id] = stages

        return pipelines

    @staticmethod
    def _extract_stages(config: Any) -> List[str]:
        if isinstance(config, Mapping):
            stages = config.get("stages")
        else:
            stages = config

        if not isinstance(stages, Iterable) or isinstance(stages, (bytes, str)):
            raise PipelineConfigError("Each pipeline entry must define a list of stages")

        return [str(stage) for stage in stages]


def _extract_interaction_id(bundle: Any) -> str | None:
    if isinstance(bundle, PipelineBundle):
        return getattr(getattr(bundle, "meta", None), "interaction_id", None)
    if isinstance(bundle, BaseModel):
        meta = getattr(bundle, "meta", None)
        if meta:
            return getattr(meta, "interaction_id", None)
    if isinstance(bundle, Mapping):
        meta = bundle.get("meta") if isinstance(bundle.get("meta"), Mapping) else None
        if meta and isinstance(meta, Mapping):
            meta_id = meta.get("interaction_id")
            if meta_id:
                return str(meta_id)
        interaction = bundle.get("interaction") if isinstance(bundle.get("interaction"), Mapping) else None
        if interaction and interaction.get("id"):
            return str(interaction.get("id"))
    return None


def _propagate_meta(previous: Any, new_bundle: Any) -> Any:
    previous_meta_id: str | None = None
    previous_meta = getattr(previous, "meta", None)
    if previous_meta is not None:
        previous_meta_id = getattr(previous_meta, "interaction_id", None)

    if isinstance(previous, PipelineBundle) and isinstance(new_bundle, PipelineBundle):
        try:
            new_bundle.bundle_version = previous.bundle_version
            new_bundle.processing_version = previous.processing_version
        except Exception:
            pass

    new_meta = getattr(new_bundle, "meta", None)
    if previous_meta_id and new_meta is not None:
        new_interaction_id = getattr(new_meta, "interaction_id", None)
        if new_interaction_id != previous_meta_id:
            try:
                new_bundle.meta.interaction_id = previous_meta_id
            except Exception:
                pass

    return new_bundle


def _log_stage(ctx: PipelineContext, stage_id: str, interaction_id: str | None, duration_ms: float, status: str, error: Exception | None = None) -> None:
    log_payload = {
        "stage_id": stage_id,
        "interaction_id": interaction_id,
        "duration_ms": round(duration_ms, 2),
        "status": status,
    }
    if status == "success":
        ctx.logger.info("pipeline_stage", extra=log_payload)
    else:
        ctx.logger.warning("pipeline_stage_failed", extra={**log_payload, "error": str(error)})


def run_pipeline(
    pipeline_id: str,
    bundle_in: BaseModel | Mapping[str, Any],
    ctx: PipelineContext,
    *,
    loader: PipelineLoader | None = None,
    registry: StageRegistry | None = None,
) -> Any:
    stage_registry = registry or STAGE_REGISTRY
    pipeline_loader = loader or PipelineLoader(stage_registry)
    pipelines = pipeline_loader.load()

    if pipeline_id not in pipelines:
        raise PipelineConfigError(f"Pipeline '{pipeline_id}' not found in registry")

    bundle: Any = bundle_in
    for stage_id in pipelines[pipeline_id]:
        stage_fn = stage_registry.get(stage_id)
        started = time.perf_counter()
        previous = bundle
        try:
            bundle = stage_fn(bundle, ctx)
            bundle = _propagate_meta(previous, bundle)
            duration_ms = (time.perf_counter() - started) * 1000
            _log_stage(ctx, stage_id, _extract_interaction_id(bundle) or _extract_interaction_id(bundle_in), duration_ms, "success")
        except Exception as exc:
            duration_ms = (time.perf_counter() - started) * 1000
            _log_stage(ctx, stage_id, _extract_interaction_id(bundle) or _extract_interaction_id(bundle_in), duration_ms, "failure", exc)
            raise PipelineStageError(stage_id, exc) from exc

    return bundle


STAGE_REGISTRY = StageRegistry()


@STAGE_REGISTRY.register("ingest.validate_input")
def stage_validate_input(bundle: Any, ctx: PipelineContext) -> RawInputBundle:
    context = ctx.to_mapping()
    if isinstance(bundle, Mapping) and not isinstance(bundle, BaseModel):
        meta = context.get("meta") or bundle.get("meta")
        interaction_id = _extract_interaction_id(bundle) or context.get("interaction_id") or context.get("request_id")
        if meta is None:
            meta = InteractionMeta(
                interaction_id=str(interaction_id or ""),
                interaction_type=str(context.get("interaction_type") or bundle.get("interaction_type") or "interaction"),
                source_uri=bundle.get("source_uri"),
                source_type=str(bundle.get("source_type") or "text"),
                created_by=str(context.get("user")) if context.get("user") else None,
            )
        bundle = RawInputBundle(meta=meta, raw_text=bundle.get("text") or bundle.get("raw_text"), metadata=bundle.get("metadata", {}))
    return legacy_stages.require_raw_input(bundle, context)


@STAGE_REGISTRY.register("ingest.parse_or_transcribe")
def stage_parse_or_transcribe(bundle: Any, ctx: PipelineContext) -> Any:
    context = ctx.to_mapping()
    if isinstance(bundle, RawInputBundle) and not bundle.raw_text and bundle.raw_file_path:
        try:
            interaction, text = doc_ingest({"source_uri": bundle.raw_file_path, "text": ""})
            bundle = RawInputBundle(meta=InteractionMeta.model_validate(interaction), raw_text=text, metadata=bundle.metadata)
        except TranscriptionFailure:
            note_data = note_ingest({"source_uri": bundle.raw_file_path, "text": ""})
            bundle = RawInputBundle(meta=InteractionMeta.model_validate(note_data[0]), raw_text=note_data[1], metadata=bundle.metadata)
    return legacy_stages.tokenise_text(bundle, context)


@STAGE_REGISTRY.register("nlp.extract")
def stage_nlp_extract(bundle: Any, ctx: PipelineContext) -> Any:
    context = ctx.to_mapping()
    extracted = legacy_stages.apply_extraction(bundle, context)
    return legacy_stages.sync_knowledgebase(extracted, context)


@STAGE_REGISTRY.register("normalise.resolve_entities")
def stage_normalise(bundle: Any, ctx: PipelineContext) -> Any:
    # Placeholder for contextual identity resolution; preserves bundle continuity.
    return bundle


@STAGE_REGISTRY.register("preview.assemble")
def stage_preview(bundle: Any, ctx: PipelineContext) -> PreviewBundle:
    context = ctx.to_mapping()
    if not isinstance(bundle, ExtractionBundle):
        raise TypeError("preview.assemble expects an ExtractionBundle")

    preview_payload = legacy_stages.build_preview_payload(bundle, context)
    preview = preview_payload if isinstance(preview_payload, PreviewBundle) else PreviewBundle.model_validate(preview_payload)

    staging_store = context.get("staging_store")
    if isinstance(staging_store, StagingStore):
        interaction_id = preview.meta.interaction_id
        staging_store.save_preview(interaction_id, preview)
        staging_store.set_state(interaction_id, "preview_ready")
        ctx.logger.info(
            "preview_ready",
            extra={"interaction_id": interaction_id, "stage": "preview.assemble"},
        )

    pending = context.get("pending_interactions")
    if isinstance(pending, MutableMapping):
        pending[preview.meta.interaction_id] = preview.model_dump(mode="json")

    return preview


@STAGE_REGISTRY.register("commit.validate")
def stage_commit_validate(bundle: Any, ctx: PipelineContext) -> Any:
    context = ctx.to_mapping()
    validated = legacy_stages.require_preview_payload(bundle, context)
    return legacy_stages.capture_preview_memory(validated, context)


@STAGE_REGISTRY.register("graph.upsert")
def stage_graph_upsert(bundle: Any, ctx: PipelineContext) -> Any:
    context = ctx.to_mapping()
    resolved = legacy_stages.resolve_entities_from_graph(bundle, context)
    interaction_bundle = legacy_stages.build_interaction_bundle_stage(resolved, context)
    return legacy_stages.upsert_interaction_bundle_stage(interaction_bundle, context)


@STAGE_REGISTRY.register("alerts.evaluate")
def stage_alerts(bundle: Any, ctx: PipelineContext) -> Any:  # pragma: no cover - placeholder
    return bundle


@STAGE_REGISTRY.register("learn.capture_feedback")
def stage_feedback(bundle: Any, ctx: PipelineContext) -> Any:
    context = ctx.to_mapping()
    return legacy_stages.persist_session_memory(bundle, context)


__all__ = [
    "DEFAULT_PIPELINE_PATH",
    "PipelineConfigError",
    "PipelineStageError",
    "PipelineContext",
    "PipelineLoader",
    "StageRegistry",
    "run_pipeline",
    "STAGE_REGISTRY",
]

# Register additional pipeline stages.
from logos.pipelines import concept_update as _concept_update  # noqa: F401,E402
from logos.pipelines import interaction_commit as _interaction_commit  # noqa: F401,E402
from logos.pipelines import reasoning_alerts as _reasoning_alerts  # noqa: F401,E402
