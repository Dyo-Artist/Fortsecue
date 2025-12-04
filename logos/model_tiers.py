from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, Mapping

import yaml

TIERS_PATH = Path(__file__).resolve().parent / "knowledgebase" / "models" / "tiers.yml"
_ALLOWED_TIERS = {"rule_only", "local_ml", "local_llm"}


class TierConfigError(RuntimeError):
    """Raised when the model tier configuration is missing or malformed."""


@dataclass(frozen=True)
class TaskTierConfig:
    """Configuration entry for a single task's model tier selection."""

    task: str
    tier: str
    fallback_tier: str | None = None


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


__all__ = [
    "TaskTierConfig",
    "TierConfigError",
    "TIERS_PATH",
    "clear_tier_cache",
    "get_task_tier",
]
