from __future__ import annotations

from copy import deepcopy
from difflib import SequenceMatcher
from datetime import datetime, timezone
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


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [item for item in value if item is not None]
    return [value]


def _extract_context_values(context: Mapping[str, Any] | None, key: str) -> list[str]:
    if not isinstance(context, Mapping):
        return []

    values: list[str] = []

    def _consume(item: Any) -> None:
        if isinstance(item, Mapping):
            for candidate_key in ("id", "name", "title", "label"):
                candidate_value = item.get(candidate_key)
                if candidate_value:
                    values.append(str(candidate_value))
        elif item:
            values.append(str(item))

    _consume(context.get(key))

    for suffix in ("id", "name", "title"):
        field_key = f"{key}_{suffix}"
        if context.get(field_key):
            values.append(str(context[field_key]))

    plural = context.get(f"{key}s")
    if isinstance(plural, list):
        for item in plural:
            _consume(item)

    return values


def _normalise_text(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    return value.strip().lower() or None


def _normalise_tokens(value: str | None) -> list[str]:
    normalised = _normalise_text(value)
    if not normalised:
        return []
    return [token for token in normalised.replace("_", " ").replace("-", " ").split() if token]


def _token_signature(tokens: Sequence[str]) -> str:
    return " ".join(sorted(tokens))


def _similarity_ratio(left: Any, right: Any) -> float:
    left_norm = _normalise_text(left)
    right_norm = _normalise_text(right)
    if left_norm is None or right_norm is None:
        return 0.0

    direct_ratio = SequenceMatcher(None, left_norm, right_norm).ratio()

    left_tokens = _normalise_tokens(left_norm)
    right_tokens = _normalise_tokens(right_norm)
    if not left_tokens or not right_tokens:
        return direct_ratio

    token_ratio = SequenceMatcher(None, _token_signature(left_tokens), _token_signature(right_tokens)).ratio()
    return max(direct_ratio, token_ratio)


def _threshold_for(thresholds: Rules, category: str, key: str, default: float) -> float:
    defaults = thresholds.get("defaults", {}) if isinstance(thresholds.get("defaults"), dict) else {}
    section = thresholds.get(category, {}) if isinstance(thresholds.get(category), dict) else {}
    return float(section.get(key, defaults.get(key, default)))


def _is_similar(thresholds: Rules, category: str, key: str, left: Any, right: Any, default: float = 1.0) -> bool:
    similarity = _similarity_ratio(left, right)
    threshold = _threshold_for(thresholds, category, key, default)
    return similarity >= threshold


def _similarity_score(thresholds: Rules, category: str, key: str, left: Any, right: Any, default: float = 1.0) -> float:
    similarity = _similarity_ratio(left, right)
    threshold = _threshold_for(thresholds, category, key, default)
    return similarity if similarity >= threshold else 0.0


def _extract_domain(value: str | None) -> str | None:
    if not value:
        return None
    text = _normalise_text(value)
    if not text:
        return None
    if "@" in text:
        return text.split("@")[-1]
    return text


def _append_history(
    entity: Mapping[str, Any],
    status: str,
    candidates: Sequence[Mapping[str, Any]],
    canonical_id: str | None,
    confidence: float,
    best_guess_id: str | None,
) -> list[Dict[str, Any]]:
    existing = entity.get("identity_history") if isinstance(entity, Mapping) else None
    history = list(existing) if isinstance(existing, list) else []
    history.append(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "canonical_id": canonical_id,
            "best_guess_id": best_guess_id,
            "confidence": confidence,
            "candidates": [
                {"id": candidate.get("id"), "score": candidate.get("score")}
                for candidate in candidates
            ],
        }
    )
    return history


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

    def _candidate_floor(self, category: str) -> float:
        defaults = self._rules.get("defaults", {}) if isinstance(self._rules.get("defaults"), dict) else {}
        section = self._rules.get(category, {}) if isinstance(self._rules.get(category), dict) else {}
        return float(section.get("candidate_floor", defaults.get("candidate_floor", 0.0)))

    def _max_alternates(self, category: str) -> int:
        defaults = self._rules.get("defaults", {}) if isinstance(self._rules.get("defaults"), dict) else {}
        section = self._rules.get(category, {}) if isinstance(self._rules.get(category), dict) else {}
        return int(section.get("max_alternates", defaults.get("max_alternates", 3)))

    def _context_rules(self, category: str) -> Mapping[str, Any]:
        defaults = self._rules.get("defaults", {}) if isinstance(self._rules.get("defaults"), dict) else {}
        section = self._rules.get(category, {}) if isinstance(self._rules.get(category), dict) else {}
        default_ctx = defaults.get("context", {}) if isinstance(defaults.get("context"), dict) else {}
        section_ctx = section.get("context", {}) if isinstance(section.get("context"), dict) else {}
        merged = dict(default_ctx)
        merged.update(section_ctx)
        return merged

    def _ambiguity_gap(self, category: str) -> float:
        return _threshold_for(self._thresholds, category, "ambiguity_gap", 0.0)

    def _context_overlap(
        self, category: str, threshold_key: str, context_values: Sequence[Any], candidate_values: Sequence[Any]
    ) -> list[Dict[str, Any]]:
        matches: list[Dict[str, Any]] = []
        for ctx_val in context_values:
            for cand_val in candidate_values:
                if _is_similar(self._thresholds, category, threshold_key, ctx_val, cand_val):
                    matches.append({"context": ctx_val, "candidate": cand_val})
        return matches

    def _contextual_bonus(
        self,
        category: str,
        candidate: Mapping[str, Any],
        preview_context: Mapping[str, Any],
        rules: Mapping[str, Any],
    ) -> tuple[float, Dict[str, Any]]:
        context_rules = self._context_rules(category)
        if not context_rules or not isinstance(preview_context, Mapping):
            return 0.0, {}

        bonus = 0.0
        hits: dict[str, Any] = {}

        project_matches = self._context_overlap(
            category,
            "project_similarity",
            _extract_context_values(preview_context, "project"),
            _as_list(candidate.get("project_ids")) + _as_list(candidate.get("project_names")),
        )
        if project_matches and "project_score" in context_rules:
            bonus += float(context_rules.get("project_score", 0.0))
            hits["projects"] = project_matches

        document_matches = self._context_overlap(
            category,
            "document_similarity",
            _extract_context_values(preview_context, "document"),
            _as_list(candidate.get("document_ids")) + _as_list(candidate.get("document_titles")),
        )
        if document_matches and "document_score" in context_rules:
            bonus += float(context_rules.get("document_score", 0.0))
            hits["documents"] = document_matches

        location_matches = self._context_overlap(
            category,
            "location_similarity",
            _extract_context_values(preview_context, "location"),
            _as_list(candidate.get("location")) + _as_list(candidate.get("region")) + _as_list(candidate.get("country")),
        )
        if location_matches and "location_score" in context_rules:
            bonus += float(context_rules.get("location_score", 0.0))
            hits["locations"] = location_matches

        return bonus, hits

    def _score_candidate(
        self,
        category: str,
        entity: Mapping[str, Any],
        candidate: Mapping[str, Any],
        preview_context: Mapping[str, Any],
    ) -> tuple[float, list[str], Dict[str, Any]]:
        rules = self._rules.get(category, {}) if isinstance(self._rules.get(category), dict) else {}

        matched_fields: list[str] = []
        components: list[float] = []

        email_similarity = _similarity_score(
            self._thresholds, category, "email_similarity", entity.get("email"), candidate.get("email")
        )
        if email_similarity:
            components.append(float(rules.get("email_score", 1.0)) * email_similarity)
            matched_fields.append("email")

        entity_domain = _extract_domain(entity.get("domain")) or _extract_domain(entity.get("email"))
        candidate_domain = _extract_domain(candidate.get("domain")) or _extract_domain(candidate.get("email"))
        if not candidate_domain:
            candidate_domain = _extract_domain(candidate.get("org_domain"))

        phone_similarity = _similarity_score(
            self._thresholds, category, "phone_similarity", entity.get("phone"), candidate.get("phone")
        )
        if phone_similarity:
            components.append(float(rules.get("phone_score", 1.0)) * phone_similarity)
            matched_fields.append("phone")

        name_similarity = _similarity_score(
            self._thresholds, category, "name_similarity", entity.get("name"), candidate.get("name")
        )
        org_similarity = _similarity_score(
            self._thresholds, category, "org_similarity", entity.get("org_id"), candidate.get("org_id")
        ) or _similarity_score(
            self._thresholds, category, "org_similarity", entity.get("org_name"), candidate.get("org_name")
        )
        domain_similarity = _similarity_score(
            self._thresholds, category, "domain_similarity", entity_domain, candidate_domain
        )

        if name_similarity and org_similarity:
            components.append(float(rules.get("name_org_score", 0.0)) * max(name_similarity, org_similarity))
            matched_fields.append("name_org")
        elif name_similarity:
            components.append(float(rules.get("name_only_score", 0.0)) * name_similarity)
            matched_fields.append("name")

        if domain_similarity:
            components.append(float(rules.get("domain_score", 0.0)) * domain_similarity)
            matched_fields.append("domain")

        if name_similarity and "name_score" in rules:
            components.append(float(rules.get("name_score", 0.0)) * name_similarity)

        base_score = sum(components) if components else 0.0
        context_bonus, context_hits = self._contextual_bonus(category, candidate, preview_context, rules)
        if context_hits:
            matched_fields.extend([f"context:{key}" for key in context_hits.keys()])

        return base_score + context_bonus, matched_fields, context_hits

    def _evaluate_candidates(
        self,
        category: str,
        entity: Mapping[str, Any],
        candidates: Sequence[Mapping[str, Any]],
        preview_context: Mapping[str, Any],
    ) -> list[Dict[str, Any]]:
        evaluated: list[Dict[str, Any]] = []
        for candidate in candidates:
            score, matched_fields, context_hits = self._score_candidate(category, entity, candidate, preview_context)
            if score <= 0 and not matched_fields and not context_hits:
                continue
            evaluated.append(
                {
                    "id": candidate.get("id"),
                    "score": score,
                    "matched_fields": matched_fields,
                    "context_hits": context_hits,
                    "candidate": candidate,
                }
            )

        evaluated.sort(key=lambda result: result.get("score", 0.0), reverse=True)
        return evaluated

    def _build_resolution(
        self,
        category: str,
        entity: Mapping[str, Any],
        evaluated: list[Dict[str, Any]],
        min_confidence: float,
    ) -> tuple[Dict[str, Any], str | None]:
        updated = dict(entity)
        existing_id = updated.get("id")
        updated["temp_id"] = existing_id

        candidate_floor = self._candidate_floor(category)
        max_alternates = self._max_alternates(category)
        ambiguity_gap = self._ambiguity_gap(category)

        candidates_above_floor = [candidate for candidate in evaluated if candidate.get("score", 0.0) >= candidate_floor]
        best = candidates_above_floor[0] if candidates_above_floor else None
        best_guess_id = best.get("id") if best else None
        confidence = float(best.get("score", 0.0)) if best else 0.0

        canonical_id: str | None = None
        status = "unresolved"
        if best and best_guess_id:
            if confidence >= min_confidence:
                canonical_id = str(best_guess_id)
                status = "resolved"
            elif len(candidates_above_floor) > 1:
                status = "ambiguous"
            else:
                status = "ambiguous"

        if canonical_id and len(candidates_above_floor) > 1:
            second = candidates_above_floor[1]
            if confidence - float(second.get("score", 0.0)) <= ambiguity_gap:
                status = "multi_resolved"

        candidate_view = [
            {
                "id": candidate.get("id"),
                "score": candidate.get("score"),
                "matched_fields": candidate.get("matched_fields", []),
                "context_hits": candidate.get("context_hits", {}),
            }
            for candidate in candidates_above_floor[: max_alternates + 1]
        ]

        updated["canonical_id"] = canonical_id
        updated["confidence"] = confidence
        updated["best_guess_id"] = best_guess_id
        if canonical_id:
            updated["id"] = canonical_id
            candidate_org = best.get("candidate", {}) if best else {}
            if candidate_org.get("org_id") and updated.get("org_id"):
                updated["org_id"] = candidate_org.get("org_id")
        updated["identity_candidates"] = candidate_view
        updated["alternates"] = [candidate for candidate in candidate_view if candidate.get("id") != canonical_id]
        updated["resolution_status"] = status
        updated["identity_history"] = _append_history(
            entity,
            status,
            candidate_view,
            canonical_id,
            confidence,
            best_guess_id,
        )
        return updated, canonical_id

    def _append_resolution_log_entry(self, log: list[Dict[str, Any]], category: str, entity: Mapping[str, Any]) -> None:
        if not isinstance(log, list):
            return

        status = entity.get("resolution_status")
        if status in (None, "resolved"):
            return

        log.append(
            {
                "category": category,
                "temp_id": entity.get("temp_id") or entity.get("id"),
                "canonical_id": entity.get("canonical_id"),
                "best_guess_id": entity.get("best_guess_id"),
                "resolution_status": status,
                "candidates": entity.get("identity_candidates", []),
                "confidence": entity.get("confidence"),
            }
        )

    def _lookup_org_candidates(self, org: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
        name = org.get("name")
        domain = org.get("domain")
        name_tokens = _normalise_tokens(name)
        if not name and not domain and not name_tokens:
            return []
        return self._run_query(
            (
                "MATCH (o:Org) "
                "OPTIONAL MATCH (o)-[:INVOLVED_IN]->(p:Project) "
                "WHERE ($name IS NOT NULL AND toLower(o.name) CONTAINS toLower($name)) "
                "   OR ($domain IS NOT NULL AND toLower(o.domain) = toLower($domain)) "
                "   OR (SIZE($name_tokens) > 0 AND ANY(token IN $name_tokens WHERE toLower(o.name) CONTAINS token)) "
                "RETURN o.id AS id, o.name AS name, o.domain AS domain, o.region AS region, o.country AS country, "
                "       collect(DISTINCT p.id) AS project_ids, collect(DISTINCT p.name) AS project_names"
            ),
            {"name": name, "domain": domain, "name_tokens": name_tokens},
        )

    def _lookup_person_candidates(self, person: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
        name = person.get("name")
        email = person.get("email")
        phone = person.get("phone")
        domain = _extract_domain(email) or _extract_domain(person.get("domain"))
        name_tokens = _normalise_tokens(name)
        if not any([name, email, phone, domain]):
            return []
        return self._run_query(
            (
                "MATCH (p:Person) "
                "OPTIONAL MATCH (p)-[:WORKS_FOR]->(o:Org) "
                "OPTIONAL MATCH (p)-[:INVOLVED_IN]->(proj:Project) "
                "WITH p, o, collect(DISTINCT proj) AS projects "
                "OPTIONAL MATCH (p)-[:PARTICIPATED_IN]->(:Interaction)-[:HAS_SOURCE]->(d:Document) "
                "WITH p, o, projects, collect(DISTINCT d) AS documents "
                "WHERE ($name IS NOT NULL AND toLower(p.name) CONTAINS toLower($name)) "
                "   OR (SIZE($name_tokens) > 0 AND ANY(token IN $name_tokens WHERE toLower(p.name) CONTAINS token)) "
                "   OR ($email IS NOT NULL AND toLower(p.email) = toLower($email)) "
                "   OR ($phone IS NOT NULL AND p.phone = $phone) "
                "   OR ($domain IS NOT NULL AND toLower(p.email) ENDS WITH $domain) "
                "   OR ($domain IS NOT NULL AND toLower(o.domain) ENDS WITH $domain) "
                "RETURN p.id AS id, p.name AS name, p.email AS email, p.phone AS phone, "
                "       o.id AS org_id, o.name AS org_name, o.domain AS org_domain, "
                "       [proj IN projects | proj.id] AS project_ids, [proj IN projects | proj.name] AS project_names, "
                "       [doc IN documents | doc.id] AS document_ids, "
                "       [doc IN documents | coalesce(doc.title, doc.name)] AS document_titles"
            ),
            {"name": name, "email": email, "phone": phone, "domain": domain, "name_tokens": name_tokens},
        )

    def _lookup_project_candidates(self, project: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
        name = project.get("name")
        if not name:
            return []
        return self._run_query(
            (
                "MATCH (p:Project) WHERE toLower(p.name) = toLower($name) "
                "RETURN p.id AS id, p.name AS name, p.location AS location, p.region AS region"
            ),
            {"name": name},
        )

    def resolve_preview(self, preview: Mapping[str, Any]) -> Dict[str, Any]:
        resolved_preview = deepcopy(preview)
        entities = resolved_preview.get("entities") if isinstance(resolved_preview, Mapping) else None
        if not isinstance(entities, Mapping):
            return resolved_preview

        preview_context = resolved_preview.get("context") if isinstance(resolved_preview, Mapping) else {}
        resolution_log = resolved_preview.get("resolution_log") if isinstance(resolved_preview.get("resolution_log"), list) else []
        resolved_preview["resolution_log"] = resolution_log

        id_map: dict[str, str] = {}

        orgs = entities.get("orgs") if isinstance(entities.get("orgs"), list) else []
        resolved_orgs = []
        for org in orgs:
            if not isinstance(org, Mapping):
                continue
            candidates = self._lookup_org_candidates(org)
            evaluated = self._evaluate_candidates("org", org, candidates, preview_context)
            updated, canonical_id = self._build_resolution("org", org, evaluated, self._min_confidence("org"))
            resolved_orgs.append(updated)
            if updated.get("temp_id") and canonical_id:
                id_map[str(updated["temp_id"])] = str(canonical_id)
            self._append_resolution_log_entry(resolution_log, "org", updated)
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
            evaluated = self._evaluate_candidates("person", person_with_org, candidates, preview_context)
            updated, canonical_id = self._build_resolution("person", person_with_org, evaluated, self._min_confidence("person"))
            resolved_persons.append(updated)
            if updated.get("temp_id") and canonical_id:
                id_map[str(updated["temp_id"])] = str(canonical_id)
            self._append_resolution_log_entry(resolution_log, "person", updated)
        entities["persons"] = resolved_persons

        projects = entities.get("projects") if isinstance(entities.get("projects"), list) else []
        resolved_projects = []
        for project in projects:
            if not isinstance(project, Mapping):
                continue
            candidates = self._lookup_project_candidates(project)
            evaluated = self._evaluate_candidates("project", project, candidates, preview_context)
            updated, canonical_id = self._build_resolution("project", project, evaluated, self._min_confidence("project"))
            resolved_projects.append(updated)
            if updated.get("temp_id") and canonical_id:
                id_map[str(updated["temp_id"])] = str(canonical_id)
            self._append_resolution_log_entry(resolution_log, "project", updated)
        entities["projects"] = resolved_projects

        relationships = resolved_preview.get("relationships") if isinstance(resolved_preview.get("relationships"), list) else []
        resolved_preview["relationships"] = _rewrite_relationships(relationships, id_map)

        return resolved_preview


def reassign_preview_identities(preview: Mapping[str, Any], reassignment: Mapping[str, str]) -> Dict[str, Any]:
    """Re-map entity identifiers in a preview and propagate the change to relationships.

    This supports delayed merge decisions by allowing callers to update the
    best-known IDs and maintain an identity history for traceability.
    """

    updated_preview = deepcopy(preview)
    if not reassignment:
        return updated_preview

    id_map = {str(k): str(v) for k, v in reassignment.items() if k and v}
    entities = updated_preview.get("entities") if isinstance(updated_preview, Mapping) else None
    if not isinstance(entities, Mapping):
        return updated_preview

    for category in ("orgs", "persons", "projects"):
        records = entities.get(category) if isinstance(entities.get(category), list) else []
        remapped: list[Dict[str, Any]] = []
        for record in records:
            if not isinstance(record, Mapping):
                continue
            updated = dict(record)
            for field in ("id", "canonical_id", "best_guess_id", "temp_id"):
                if updated.get(field) in id_map:
                    updated[field] = id_map[updated[field]]
            candidates = updated.get("identity_candidates") if isinstance(updated.get("identity_candidates"), list) else []
            refreshed_candidates: list[Dict[str, Any]] = []
            for candidate in candidates:
                if not isinstance(candidate, Mapping):
                    continue
                candidate_copy = dict(candidate)
                if candidate_copy.get("id") in id_map:
                    candidate_copy["id"] = id_map[candidate_copy["id"]]
                refreshed_candidates.append(candidate_copy)
            updated["identity_candidates"] = refreshed_candidates
            updated["alternates"] = [candidate for candidate in refreshed_candidates if candidate.get("id") != updated.get("canonical_id")]
            updated["identity_history"] = _append_history(
                updated,
                "reassigned",
                refreshed_candidates,
                updated.get("canonical_id"),
                float(updated.get("confidence", 0.0)),
                updated.get("best_guess_id"),
            )
            remapped.append(updated)
        entities[category] = remapped

    relationships = updated_preview.get("relationships") if isinstance(updated_preview.get("relationships"), list) else []
    updated_preview["relationships"] = _rewrite_relationships(relationships, id_map)

    resolution_log = updated_preview.get("resolution_log") if isinstance(updated_preview.get("resolution_log"), list) else []
    resolution_log.append({"category": "reassignment", "resolution_status": "reassigned", "id_map": id_map})
    updated_preview["resolution_log"] = resolution_log

    return updated_preview


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
