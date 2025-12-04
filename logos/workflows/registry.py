from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping

import yaml

PIPELINES_PATH = Path(__file__).resolve().parent.parent / "knowledgebase" / "workflows" / "pipelines.yml"


class PipelineConfigError(RuntimeError):
    """Raised when the pipeline configuration is missing or malformed."""


class PipelineNotFound(KeyError):
    """Raised when a pipeline id is not declared in the registry."""


class StageResolutionError(RuntimeError):
    """Raised when a stage callable cannot be resolved from the registry."""


def _coerce_pipeline_mapping(raw: Mapping[str, Any]) -> Dict[str, List[str]]:
    pipelines: Dict[str, List[str]] = {}
    for pipeline_id, stages in raw.items():
        if not isinstance(stages, Iterable) or isinstance(stages, (str, bytes)):
            raise PipelineConfigError("Each pipeline must be a list of stage function names")
        str_stages: List[str] = []
        for stage in stages:
            if not isinstance(stage, str):
                raise PipelineConfigError("Stage entries must be strings")
            str_stages.append(stage)
        pipelines[pipeline_id] = str_stages
    return pipelines


def load_pipeline_config(path: Path | None = None) -> Dict[str, List[str]]:
    """Load pipeline definitions from the YAML registry."""

    target = path or PIPELINES_PATH
    if not target.exists():
        raise PipelineConfigError(f"Pipeline registry missing at {target}")

    try:
        with target.open("r", encoding="utf-8") as file:
            raw_data = yaml.safe_load(file) or {}
    except yaml.YAMLError as exc:  # pragma: no cover - defensive guard
        raise PipelineConfigError("Failed to parse pipeline registry YAML") from exc

    if not isinstance(raw_data, Mapping):
        raise PipelineConfigError("Pipeline registry must be a mapping of pipeline ids")

    return _coerce_pipeline_mapping(raw_data)


def _resolve_callable(path: str) -> Callable[[Any, Dict[str, Any] | None], Any]:
    module_path, _, func_name = path.rpartition(".")
    if not module_path:
        raise StageResolutionError(f"Invalid stage reference '{path}'")
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:  # pragma: no cover - import guard
        raise StageResolutionError(f"Unable to import stage module '{module_path}'") from exc

    try:
        func = getattr(module, func_name)
    except AttributeError as exc:  # pragma: no cover - attr guard
        raise StageResolutionError(f"Stage function '{func_name}' not found in '{module_path}'") from exc

    if not callable(func):
        raise StageResolutionError(f"Stage reference '{path}' is not callable")

    return func


def run_pipeline(pipeline_id: str, bundle_in: Any, context: Dict[str, Any] | None = None) -> Any:
    """Execute the configured pipeline by calling each stage in order."""

    pipelines = load_pipeline_config()
    if pipeline_id not in pipelines:
        raise PipelineNotFound(f"Pipeline '{pipeline_id}' not found")

    ctx = context if context is not None else {}
    bundle = bundle_in
    for stage_name in pipelines[pipeline_id]:
        stage_fn = _resolve_callable(stage_name)
        try:
            bundle = stage_fn(bundle, ctx)
        except TypeError:
            bundle = stage_fn(bundle)
    return bundle


__all__ = [
    "PIPELINES_PATH",
    "PipelineConfigError",
    "PipelineNotFound",
    "StageResolutionError",
    "load_pipeline_config",
    "run_pipeline",
]

