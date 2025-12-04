from __future__ import annotations

from copy import deepcopy
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Mapping, Sequence

import yaml

from logos.graphio.neo4j_client import GraphUnavailable

Rules = Dict[str, Any]
QueryRunner = Callable[[str, Dict[str, Any]], Sequence[Mapping[str, Any]]]

RULES_PATH = Path(__file__).resolve().parent.parent / "knowledgebase" / "rules" / "entity_resolution.yml"
MERGE_THRESHOLDS_PATH = Path(__file__).resolve().parent.parent / "knowledgebase" / "rules" / "merge_thresholds.yml"


class ResolutionConfigError(RuntimeError):
    """Raised when the entity resolution rules cannot be loaded."""


def _load_rules(path: Path = RULES_PATH) -> Rules:
    if not path.exists():
        raise ResolutionConfigError(f"Resolution rules not found at {path}")

    try:
        with path.open("r", encoding="utf-8") as file:
            data = yaml.safe_load(file) or {}
    except yaml.YAMLError as exc:  # pragma: no cover - defensive
        raise ResolutionConfigError("Failed to parse entity resolution rules") from exc

    if not isinstance(data, dict):
        raise ResolutionConfigError("Resolution rules must be a mapping")

    return data


def _load_thresholds(path: Path = MERGE_THRESHOLDS_PATH) -> Rules:
    if not path.exists():
        raise ResolutionConfigError(f"Merge thresholds not found at {path}")

    try:
        with path.open("r", encoding="utf-8") as file:
            data = yaml.safe_load(file) or {}
    except yaml.YAMLError as exc:  # pragma: no cover - defensive
        raise ResolutionConfigError("Failed to parse merge thresholds rules") from exc

    if not isinstance(data, dict):
        raise ResolutionConfigError("Merge thresholds must be a mapping")

    return data


def _normalise_text(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    return value.strip().lower() or None


def _threshold_for(thresholds: Rules, category: str, key: str, default: float) -> float:
    defaults = thresholds.get("defaults", {}) if isinstance(thresholds.get("defaults"), dict) else {}
    section = thresholds.get(category, {}) if isinstance(thresholds.get(category), dict) else {}
    return float(section.get(key, defaults.get(key, default)))


def _is_similar(thresholds: Rules, category: str, key: str, left: Any, right: Any, default: float = 1.0) -> bool:
    left_norm = _normalise_text(left)
    right_norm = _normalise_text(right)
    if left_norm is None or right_norm is None:
        return False

    threshold = _threshold_for(thresholds, category, key, default)
    similarity = SequenceMatcher(None, left_norm, right_norm).ratio()
    return similarity >= threshold


def _merge_resolution(entity: Mapping[str, Any], candidate: Mapping[str, Any], score: float) -> Dict[str, Any]:
    updated = dict(entity)
    existing_id = updated.get("id")
    updated["temp_id"] = existing_id
    updated["canonical_id"] = candidate.get("id")
    updated["confidence"] = score
    if candidate.get("id"):
        updated["id"] = candidate["id"]
    if candidate.get("org_id") and updated.get("org_id"):
        updated["org_id"] = candidate.get("org_id")
    return updated


def _rewrite_relationships(relations: Iterable[Mapping[str, Any]], id_map: Mapping[str, str]) -> list[Dict[str, Any]]:
    rewritten: list[Dict[str, Any]] = []
    for rel in relations:
        if not isinstance(rel, Mapping):
            continue
        updated = dict(rel)
        if updated.get("src") in id_map:
            updated["src"] = id_map[updated["src"]]
        if updated.get("dst") in id_map:
            updated["dst"] = id_map[updated["dst"]]
        rewritten.append(updated)
    return rewritten


class GraphEntityResolver:
    """Resolve extracted entities to canonical graph IDs using configurable rules."""

    def __init__(self, run_query: QueryRunner, rules: Rules | None = None, thresholds: Rules | None = None) -> None:
        self._run_query = run_query
        self._rules = rules or _load_rules()
        self._thresholds = thresholds or _load_thresholds()

    def _min_confidence(self, category: str) -> float:
        defaults = self._rules.get("defaults", {}) if isinstance(self._rules.get("defaults"), dict) else {}
        section = self._rules.get(category, {}) if isinstance(self._rules.get(category), dict) else {}
        return float(section.get("min_confidence", defaults.get("min_confidence", 1.0)))

    def _score_candidate(self, category: str, entity: Mapping[str, Any], candidate: Mapping[str, Any]) -> float:
        rules = self._rules.get(category, {}) if isinstance(self._rules.get(category), dict) else {}

        score = 0.0
        if _is_similar(self._thresholds, category, "email_similarity", entity.get("email"), candidate.get("email")):
            score = max(score, float(rules.get("email_score", 1.0)))
        if _is_similar(self._thresholds, category, "phone_similarity", entity.get("phone"), candidate.get("phone")):
            score = max(score, float(rules.get("phone_score", 1.0)))

        name_match = _is_similar(
            self._thresholds, category, "name_similarity", entity.get("name"), candidate.get("name")
        )
        org_match = _is_similar(
            self._thresholds, category, "org_similarity", entity.get("org_id"), candidate.get("org_id")
        ) or _is_similar(
            self._thresholds, category, "org_similarity", entity.get("org_name"), candidate.get("org_name")
        )

        if name_match and org_match:
            score = max(score, float(rules.get("name_org_score", 0.0)))
        elif name_match:
            score = max(score, float(rules.get("name_only_score", 0.0)))

        if _is_similar(
            self._thresholds, category, "domain_similarity", entity.get("domain"), candidate.get("domain")
        ):
            score = max(score, float(rules.get("domain_score", 0.0)))

        if name_match and "name_score" in rules:
            score = max(score, float(rules.get("name_score", 0.0)))

        return score

    def _best_candidate(
        self, category: str, entity: Mapping[str, Any], candidates: Sequence[Mapping[str, Any]]
    ) -> tuple[Mapping[str, Any] | None, float]:
        best: Mapping[str, Any] | None = None
        best_score = 0.0
        for candidate in candidates:
            score = self._score_candidate(category, entity, candidate)
            if score > best_score:
                best = candidate
                best_score = score
        return best, best_score

    def _lookup_org_candidates(self, org: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
        name = org.get("name")
        domain = org.get("domain")
        if not name and not domain:
            return []
        return self._run_query(
            (
                "MATCH (o:Org) "
                "WHERE ($name IS NOT NULL AND toLower(o.name) = toLower($name)) "
                "   OR ($domain IS NOT NULL AND toLower(o.domain) = toLower($domain)) "
                "RETURN o.id AS id, o.name AS name, o.domain AS domain"
            ),
            {"name": name, "domain": domain},
        )

    def _lookup_person_candidates(self, person: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
        name = person.get("name")
        email = person.get("email")
        phone = person.get("phone")
        if not any([name, email, phone]):
            return []
        return self._run_query(
            (
                "MATCH (p:Person) "
                "OPTIONAL MATCH (p)-[:WORKS_FOR]->(o:Org) "
                "WHERE ($name IS NOT NULL AND toLower(p.name) = toLower($name)) "
                "   OR ($email IS NOT NULL AND toLower(p.email) = toLower($email)) "
                "   OR ($phone IS NOT NULL AND p.phone = $phone) "
                "RETURN p.id AS id, p.name AS name, p.email AS email, p.phone AS phone, o.id AS org_id, o.name AS org_name"
            ),
            {"name": name, "email": email, "phone": phone},
        )

    def _lookup_project_candidates(self, project: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
        name = project.get("name")
        if not name:
            return []
        return self._run_query(
            "MATCH (p:Project) WHERE toLower(p.name) = toLower($name) RETURN p.id AS id, p.name AS name",
            {"name": name},
        )

    def resolve_preview(self, preview: Mapping[str, Any]) -> Dict[str, Any]:
        resolved_preview = deepcopy(preview)
        entities = resolved_preview.get("entities") if isinstance(resolved_preview, Mapping) else None
        if not isinstance(entities, Mapping):
            return resolved_preview

        id_map: dict[str, str] = {}

        orgs = entities.get("orgs") if isinstance(entities.get("orgs"), list) else []
        resolved_orgs = []
        for org in orgs:
            if not isinstance(org, Mapping):
                continue
            candidates = self._lookup_org_candidates(org)
            best, score = self._best_candidate("org", org, candidates)
            if best and score >= self._min_confidence("org"):
                updated = _merge_resolution(org, best, score)
                resolved_orgs.append(updated)
                if updated.get("temp_id") and updated.get("id"):
                    id_map[str(updated["temp_id"])] = str(updated["id"])
            else:
                resolved_orgs.append(dict(org))
        entities["orgs"] = resolved_orgs

        persons = entities.get("persons") if isinstance(entities.get("persons"), list) else []
        resolved_persons = []
        for person in persons:
            if not isinstance(person, Mapping):
                continue
            person_with_org = dict(person)
            if person_with_org.get("org_id") in id_map:
                person_with_org["org_id"] = id_map[person_with_org["org_id"]]
            candidates = self._lookup_person_candidates(person_with_org)
            best, score = self._best_candidate("person", person_with_org, candidates)
            if best and score >= self._min_confidence("person"):
                updated = _merge_resolution(person_with_org, best, score)
                resolved_persons.append(updated)
                if updated.get("temp_id") and updated.get("id"):
                    id_map[str(updated["temp_id"])] = str(updated["id"])
            else:
                resolved_persons.append(person_with_org)
        entities["persons"] = resolved_persons

        projects = entities.get("projects") if isinstance(entities.get("projects"), list) else []
        resolved_projects = []
        for project in projects:
            if not isinstance(project, Mapping):
                continue
            candidates = self._lookup_project_candidates(project)
            best, score = self._best_candidate("project", project, candidates)
            if best and score >= self._min_confidence("project"):
                updated = _merge_resolution(project, best, score)
                resolved_projects.append(updated)
                if updated.get("temp_id") and updated.get("id"):
                    id_map[str(updated["temp_id"])] = str(updated["id"])
            else:
                resolved_projects.append(dict(project))
        entities["projects"] = resolved_projects

        relationships = resolved_preview.get("relationships") if isinstance(resolved_preview.get("relationships"), list) else []
        resolved_preview["relationships"] = _rewrite_relationships(relationships, id_map)

        return resolved_preview


def resolve_preview_from_graph(
    preview: Mapping[str, Any],
    *,
    client_factory: Callable[[], Any],
) -> Dict[str, Any]:
    """Resolve entities in a preview payload using the graph as the source of truth."""

    try:
        client = client_factory()
    except GraphUnavailable:
        return dict(preview)

    if not hasattr(client, "run"):
        return dict(preview)

    resolver = GraphEntityResolver(client.run)
    try:
        return resolver.resolve_preview(preview)
    except GraphUnavailable:
        return dict(preview)

