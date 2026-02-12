"""Normalise entity hints against the active knowledgebase taxonomy."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from logos.learning.embeddings.concept_assignment import ConceptAssignmentEngine, ConceptAssignmentSettings

DEFAULT_KB_PATH = Path(__file__).resolve().parent.parent / "knowledgebase"
DEFAULT_DOMAIN_PROFILE = DEFAULT_KB_PATH / "domain_profiles" / "stakeholder_engagement.yml"


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
    """Resolve hint strings to concept IDs using embedding-first matching."""

    def __init__(
        self,
        *,
        domain_profile_path: Path = DEFAULT_DOMAIN_PROFILE,
        thresholds: Mapping[str, Any] | None = None,
    ) -> None:
        self.domain_profile_path = domain_profile_path
        self.thresholds = thresholds or {}
        self._concept_cache: dict[str, list[dict[str, Any]]] = {}
        self._assignment_engines: dict[str, ConceptAssignmentEngine] = {}

    def _concepts(self, concept_key: str) -> list[dict[str, Any]]:
        if concept_key not in self._concept_cache:
            self._concept_cache[concept_key] = _load_concept_entries(
                concept_key, domain_profile_path=self.domain_profile_path
            )
        return self._concept_cache[concept_key]

    def _assignment_engine(self, concept_key: str) -> ConceptAssignmentEngine:
        if concept_key not in self._assignment_engines:
            settings = ConceptAssignmentSettings.from_thresholds(self.thresholds, concept_key)
            self._assignment_engines[concept_key] = ConceptAssignmentEngine(settings)
        return self._assignment_engines[concept_key]

    def resolve(
        self,
        concept_key: str,
        value: str | None,
        *,
        context: Mapping[str, Any] | None = None,
        value_embedding: Sequence[float] | None = None,
    ) -> dict[str, Any] | None:
        if not value:
            return None
        engine = self._assignment_engine(concept_key)
        return engine.assign(
            concept_key=concept_key,
            value=value,
            candidates=self._concepts(concept_key),
            context=context,
            value_embedding=value_embedding,
        )

    def _apply_to_entity(
        self,
        entity: Mapping[str, Any],
        *,
        concept_key: str,
        hint_value: str | None,
        target_field: str,
    ) -> dict[str, Any]:
        updated = dict(entity)
        result = self.resolve(
            concept_key,
            hint_value,
            context={"entity_type": updated.get("type") or updated.get("kind")},
            value_embedding=updated.get("embedding"),
        )
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
