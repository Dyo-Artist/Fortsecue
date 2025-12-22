"""Normalise entity hints against the active knowledgebase taxonomy."""

from __future__ import annotations

from copy import deepcopy
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

DEFAULT_KB_PATH = Path(__file__).resolve().parent.parent / "knowledgebase"
DEFAULT_DOMAIN_PROFILE = DEFAULT_KB_PATH / "domain_profiles" / "stakeholder_engagement.yml"


def _normalise_text(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    return value.strip().lower() or None


def _similarity_ratio(left: Any, right: Any) -> float:
    left_norm = _normalise_text(left)
    right_norm = _normalise_text(right)
    if left_norm is None or right_norm is None:
        return 0.0
    return SequenceMatcher(None, left_norm, right_norm).ratio()


def _threshold_for(thresholds: Mapping[str, Any], category: str, key: str, default: float) -> float:
    defaults = thresholds.get("defaults", {}) if isinstance(thresholds.get("defaults"), dict) else {}
    section = thresholds.get(category, {}) if isinstance(thresholds.get(category), dict) else {}
    return float(section.get(key, defaults.get(key, default)))


class TaxonomyConfigError(RuntimeError):
    """Raised when taxonomy assets cannot be loaded."""


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise TaxonomyConfigError(f"Knowledgebase file not found at {path}")
    try:
        with path.open("r", encoding="utf-8") as file:
            data = yaml.safe_load(file) or {}
    except yaml.YAMLError as exc:  # pragma: no cover - defensive
        raise TaxonomyConfigError(f"Failed to parse knowledgebase file {path}") from exc

    if not isinstance(data, dict):
        raise TaxonomyConfigError(f"Knowledgebase file {path} must contain a mapping")
    return data


def _concept_file_for(concept_key: str, *, domain_profile_path: Path = DEFAULT_DOMAIN_PROFILE) -> Path:
    profile = _load_yaml(domain_profile_path)
    concept_files = profile.get("concept_files") if isinstance(profile.get("concept_files"), Mapping) else {}
    rel_path = concept_files.get(concept_key)
    if not rel_path:
        return DEFAULT_KB_PATH / "concepts" / f"{concept_key}.yml"
    return (domain_profile_path.parent / rel_path).resolve()


def _load_concept_entries(concept_key: str, *, domain_profile_path: Path = DEFAULT_DOMAIN_PROFILE) -> list[dict[str, Any]]:
    path = _concept_file_for(concept_key, domain_profile_path=domain_profile_path)
    data = _load_yaml(path)
    entries = data.get(concept_key) if isinstance(data.get(concept_key), Sequence) else []
    return [entry for entry in entries if isinstance(entry, Mapping)]


class TaxonomyNormaliser:
    """Resolve hint strings to concept IDs using deterministic and fuzzy matching."""

    def __init__(
        self,
        *,
        domain_profile_path: Path = DEFAULT_DOMAIN_PROFILE,
        thresholds: Mapping[str, Any] | None = None,
    ) -> None:
        self.domain_profile_path = domain_profile_path
        self.thresholds = thresholds or {}
        self._concept_cache: dict[str, list[dict[str, Any]]] = {}

    def _concepts(self, concept_key: str) -> list[dict[str, Any]]:
        if concept_key not in self._concept_cache:
            self._concept_cache[concept_key] = _load_concept_entries(
                concept_key, domain_profile_path=self.domain_profile_path
            )
        return self._concept_cache[concept_key]

    def _score_concept(self, value: str, entry: Mapping[str, Any], threshold: float) -> tuple[float, str]:
        value_norm = _normalise_text(value) or ""
        entry_id = _normalise_text(entry.get("id")) or ""
        entry_name = _normalise_text(entry.get("name")) or entry_id
        aliases = entry.get("aliases") if isinstance(entry.get("aliases"), (list, tuple, set)) else []
        alias_norm = {_normalise_text(alias) for alias in aliases if _normalise_text(alias)}

        if value_norm and value_norm == entry_id:
            return 1.0, "id"
        if value_norm and value_norm == entry_name:
            return 0.98, "name"
        if value_norm and value_norm in alias_norm:
            return 0.96, "alias"

        similarity = _similarity_ratio(value_norm, entry_name)
        if similarity >= threshold:
            return similarity, "fuzzy"

        return 0.0, "none"

    def resolve(self, concept_key: str, value: str | None) -> dict[str, Any] | None:
        if not value:
            return None
        candidates: list[dict[str, Any]] = []
        threshold = _threshold_for(self.thresholds, concept_key, "concept_similarity", 0.75)
        ambiguity_gap = _threshold_for(self.thresholds, concept_key, "ambiguity_gap", 0.1)

        for entry in self._concepts(concept_key):
            score, match_type = self._score_concept(value, entry, threshold)
            if score <= 0:
                continue
            candidates.append(
                {
                    "id": entry.get("id"),
                    "name": entry.get("name"),
                    "score": float(score),
                    "match_type": match_type,
                }
            )

        if not candidates:
            return {
                "source": value,
                "canonical_id": None,
                "name": None,
                "score": 0.0,
                "status": "unmatched",
                "candidates": [],
            }

        candidates.sort(key=lambda item: item.get("score", 0.0), reverse=True)
        best = candidates[0]
        second_score = candidates[1].get("score", 0.0) if len(candidates) > 1 else 0.0
        status = "matched" if best.get("score", 0.0) > 0 else "unmatched"
        if best.get("score", 0.0) - second_score <= ambiguity_gap and len(candidates) > 1:
            status = "ambiguous"

        return {
            "source": value,
            "canonical_id": best.get("id") if status == "matched" else None,
            "name": best.get("name") if status == "matched" else None,
            "score": float(best.get("score", 0.0)),
            "status": status,
            "candidates": candidates,
        }

    def _apply_to_entity(
        self,
        entity: Mapping[str, Any],
        *,
        concept_key: str,
        hint_value: str | None,
        target_field: str,
    ) -> dict[str, Any]:
        updated = dict(entity)
        result = self.resolve(concept_key, hint_value)
        if not result:
            return updated

        hints = updated.get("hint_resolution") if isinstance(updated.get("hint_resolution"), Mapping) else {}
        hints = dict(hints)
        hints[concept_key] = result
        updated["hint_resolution"] = hints

        if result.get("canonical_id"):
            updated[target_field] = result["canonical_id"]
        return updated

    def _normalise_person_or_org(self, record: Mapping[str, Any]) -> dict[str, Any]:
        hints = record.get("hints") if isinstance(record.get("hints"), Mapping) else {}
        hint_value = hints.get("stakeholder_type") or hints.get("role") or record.get("type") or record.get("role")
        return self._apply_to_entity(record, concept_key="stakeholder_types", hint_value=hint_value, target_field="type")

    def _normalise_risk(self, record: Mapping[str, Any]) -> dict[str, Any]:
        hints = record.get("hints") if isinstance(record.get("hints"), Mapping) else {}
        hint_value = (
            hints.get("category")
            or hints.get("type")
            or record.get("category")
            or record.get("type")
            or record.get("title")
        )
        return self._apply_to_entity(record, concept_key="risk_categories", hint_value=hint_value, target_field="category")

    def normalise_preview(self, preview: Mapping[str, Any]) -> dict[str, Any]:
        updated_preview = deepcopy(preview)
        entities = updated_preview.get("entities") if isinstance(updated_preview, Mapping) else None
        if not isinstance(entities, Mapping):
            return updated_preview

        persons = entities.get("persons") if isinstance(entities.get("persons"), list) else []
        entities["persons"] = [self._normalise_person_or_org(person) for person in persons if isinstance(person, Mapping)]

        orgs = entities.get("orgs") if isinstance(entities.get("orgs"), list) else []
        entities["orgs"] = [self._normalise_person_or_org(org) for org in orgs if isinstance(org, Mapping)]

        risks = entities.get("risks") if isinstance(entities.get("risks"), list) else []
        entities["risks"] = [self._normalise_risk(risk) for risk in risks if isinstance(risk, Mapping)]

        updated_preview["entities"] = entities
        return updated_preview

