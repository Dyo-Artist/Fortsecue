from __future__ import annotations
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Mapping

import logging

import yaml

TIERS_PATH = Path(__file__).resolve().parent / "knowledgebase" / "models" / "tiers.yml"
MODEL_CONFIG_PATH = Path(__file__).resolve().parent / "knowledgebase" / "models" / "catalog.yml"
_ALLOWED_TIERS = {"rule_only", "local_ml", "local_llm"}

LOGGER = logging.getLogger(__name__)


class TierConfigError(RuntimeError):
    """Raised when the model tier configuration is missing or malformed."""


@dataclass(frozen=True)
class TaskTierConfig:
    """Configuration entry for a single task's model tier selection."""

    task: str
    tier: str
    fallback_tier: str | None = None


@dataclass(frozen=True)
class ModelDefinition:
    """Definition of a specific model implementation."""

    name: str
    parameters: Mapping[str, Any]


@dataclass(frozen=True)
class ModelSelection:
    """Resolved model choice for a task and tier."""

    task: str
    tier: str
    name: str
    parameters: Mapping[str, Any]


class ModelConfigError(RuntimeError):
    """Raised when a model configuration file is missing or malformed."""


@lru_cache(maxsize=4)
def _load_tier_map(path: str) -> Dict[str, TaskTierConfig]:
    tiers_path = Path(path)
    if not tiers_path.exists():
        raise TierConfigError(f"Model tier config missing at {tiers_path}")

    try:
        with tiers_path.open("r", encoding="utf-8") as file:
            raw = yaml.safe_load(file) or {}
    except yaml.YAMLError as exc:  # pragma: no cover - defensive branch
        raise TierConfigError("Failed to parse model tier YAML") from exc

    if not isinstance(raw, Mapping):
        raise TierConfigError("Model tier config must be a mapping")

    tasks = raw.get("tasks")
    if not isinstance(tasks, Mapping):
        raise TierConfigError("Model tier config must include a 'tasks' mapping")

    parsed: Dict[str, TaskTierConfig] = {}
    for task, entry in tasks.items():
        if not isinstance(entry, Mapping):
            raise TierConfigError(f"Task '{task}' must map to a tier configuration")

        tier = entry.get("tier")
        fallback_tier = entry.get("fallback_tier")

        if not isinstance(tier, str):
            raise TierConfigError(f"Task '{task}' must declare a tier")
        if tier not in _ALLOWED_TIERS:
            raise TierConfigError(f"Task '{task}' uses unsupported tier '{tier}'")

        if fallback_tier is not None:
            if not isinstance(fallback_tier, str):
                raise TierConfigError(f"Task '{task}' fallback tier must be a string if provided")
            if fallback_tier not in _ALLOWED_TIERS:
                raise TierConfigError(
                    f"Task '{task}' uses unsupported fallback tier '{fallback_tier}'"
                )

        parsed[task] = TaskTierConfig(task=task, tier=tier, fallback_tier=fallback_tier)

    return parsed


def get_task_tier(task: str, path: Path | None = None) -> TaskTierConfig:
    """Return the configured tier selection for the requested task."""

    tiers_path = path or TIERS_PATH
    tier_map = _load_tier_map(str(tiers_path))
    try:
        return tier_map[task]
    except KeyError as exc:
        raise TierConfigError(f"Task '{task}' not defined in model tier config") from exc


def clear_tier_cache() -> None:
    """Clear cached tier maps, primarily for testing overrides."""

    _load_tier_map.cache_clear()


def _parse_model_definition(entry: Any, *, context: str) -> ModelDefinition:
    """Parse a model definition entry from YAML content."""

    if isinstance(entry, str):
        return ModelDefinition(name=entry, parameters={})

    if not isinstance(entry, Mapping):
        raise ModelConfigError(f"{context} must be a string or mapping")

    name = entry.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ModelConfigError(f"{context} must declare a non-empty model name")

    parameters = entry.get("parameters") or {}
    if not isinstance(parameters, Mapping):
        raise ModelConfigError(f"{context} parameters must be a mapping if provided")

    return ModelDefinition(name=name, parameters=dict(parameters))


@lru_cache(maxsize=4)
def _load_model_catalog(path: str) -> tuple[Dict[str, ModelDefinition], Dict[str, Dict[str, ModelDefinition]]]:
    catalog_path = Path(path)
    if not catalog_path.exists():
        raise ModelConfigError(f"Model config missing at {catalog_path}")

    try:
        with catalog_path.open("r", encoding="utf-8") as file:
            raw = yaml.safe_load(file) or {}
    except yaml.YAMLError as exc:  # pragma: no cover - defensive branch
        raise ModelConfigError("Failed to parse model config YAML") from exc

    if not isinstance(raw, Mapping):
        raise ModelConfigError("Model config must be a mapping")

    defaults_raw = raw.get("defaults", {})
    if not isinstance(defaults_raw, Mapping):
        raise ModelConfigError("Model config 'defaults' must be a mapping if provided")

    tasks_raw = raw.get("tasks")
    if not isinstance(tasks_raw, Mapping):
        raise ModelConfigError("Model config must include a 'tasks' mapping")

    defaults: Dict[str, ModelDefinition] = {}
    for tier, entry in defaults_raw.items():
        if tier not in _ALLOWED_TIERS:
            raise ModelConfigError(f"Unsupported tier '{tier}' in model defaults")
        defaults[tier] = _parse_model_definition(entry, context=f"Default tier '{tier}'")

    tasks: Dict[str, Dict[str, ModelDefinition]] = {}
    for task, tiers in tasks_raw.items():
        if tiers is None:
            tasks[task] = {}
            continue

        if not isinstance(tiers, Mapping):
            raise ModelConfigError(f"Task '{task}' model config must be a mapping")

        parsed_tiers: Dict[str, ModelDefinition] = {}
        for tier, entry in tiers.items():
            if tier not in _ALLOWED_TIERS:
                raise ModelConfigError(
                    f"Task '{task}' uses unsupported tier '{tier}' in model config"
                )
            parsed_tiers[tier] = _parse_model_definition(
                entry, context=f"Task '{task}' tier '{tier}'"
            )

        tasks[task] = parsed_tiers

    return defaults, tasks


def _select_model(
    task: str, tier: str, catalog: tuple[Dict[str, ModelDefinition], Dict[str, Dict[str, ModelDefinition]]]
) -> ModelSelection | None:
    defaults, tasks = catalog
    task_models = tasks.get(task, {})
    model_def = task_models.get(tier) or defaults.get(tier)
    if model_def is None:
        return None

    return ModelSelection(task=task, tier=tier, name=model_def.name, parameters=model_def.parameters)


def get_model_for(
    task: str, *, tiers_path: Path | None = None, model_config_path: Path | None = None
) -> ModelSelection:
    """Return the configured model for the given task with tier fallback handling."""

    tier_config = get_task_tier(task, path=tiers_path)
    catalog_path = model_config_path or MODEL_CONFIG_PATH
    catalog = _load_model_catalog(str(catalog_path))

    selection = _select_model(task, tier_config.tier, catalog)
    if selection:
        return selection

    if tier_config.fallback_tier:
        LOGGER.info(
            "Falling back to tier '%s' for task '%s' due to missing model configuration",
            tier_config.fallback_tier,
            task,
        )
        fallback_selection = _select_model(task, tier_config.fallback_tier, catalog)
        if fallback_selection:
            return fallback_selection

    raise ModelConfigError(
        f"No model configured for task '{task}' using tier '{tier_config.tier}'"
    )


def clear_model_cache() -> None:
    """Clear cached model configurations, primarily for testing overrides."""

    _load_model_catalog.cache_clear()


__all__ = [
    "TaskTierConfig",
    "TierConfigError",
    "TIERS_PATH",
    "MODEL_CONFIG_PATH",
    "ModelConfigError",
    "ModelDefinition",
    "ModelSelection",
    "clear_tier_cache",
    "clear_model_cache",
    "get_task_tier",
    "get_model_for",
]
