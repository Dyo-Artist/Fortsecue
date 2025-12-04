from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable

from logos.graphio.upsert import (
    CommitmentModel,
    ContractModel,
    ConceptModel,
    EntitiesModel,
    InteractionBundle,
    InteractionModel,
    OrgModel,
    PersonModel,
    ProjectModel,
    RelationshipModel,
    TopicModel,
)


def _normalise_entity_list(
    entries: Iterable[Any],
    *,
    id_fallbacks: tuple[str, ...] = ("id",),
    name_field: str = "name",
) -> list[dict[str, Any]]:
    normalised: list[dict[str, Any]] = []
    for entry in entries:
        if isinstance(entry, str):
            normalised.append({"id": entry, name_field: entry})
            continue
        if isinstance(entry, dict):
            entity_id = next((entry.get(key) for key in id_fallbacks if entry.get(key)), None)
            if not entity_id:
                continue
            record = dict(entry)
            record["id"] = entity_id
            if name_field not in record and entry.get("name"):
                record[name_field] = entry["name"]
            if name_field not in record and entry.get("text") and name_field != "text":
                record[name_field] = entry["text"]
            if name_field not in record:
                record[name_field] = entity_id
            normalised.append(record)
    return normalised


def _parse_datetime(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def build_interaction_bundle(interaction_id: str, preview: Dict[str, Any]) -> InteractionBundle:
    interaction_raw = preview.get("interaction", {}) if isinstance(preview, dict) else {}
    interaction = InteractionModel(
        id=interaction_raw.get("id") or interaction_id,
        type=interaction_raw.get("type") or "",
        at=_parse_datetime(interaction_raw.get("at")),
        sentiment=interaction_raw.get("sentiment"),
        summary=interaction_raw.get("summary"),
        source_uri=interaction_raw.get("source_uri"),
    )

    entities_raw = preview.get("entities", {}) if isinstance(preview, dict) else {}

    orgs = [OrgModel.model_validate(item) for item in _normalise_entity_list(entities_raw.get("orgs", []), name_field="name")]
    persons = [
        PersonModel.model_validate(item)
        for item in _normalise_entity_list(entities_raw.get("persons", []), name_field="name")
    ]
    projects = [
        ProjectModel.model_validate(item)
        for item in _normalise_entity_list(entities_raw.get("projects", []), name_field="name")
    ]
    contracts = [
        ContractModel.model_validate(item)
        for item in _normalise_entity_list(entities_raw.get("contracts", []), name_field="name")
    ]
    stakeholder_types = [
        ConceptModel.model_validate(dict(item, kind="StakeholderType"))
        for item in _normalise_entity_list(entities_raw.get("stakeholder_types", []), name_field="name")
    ]
    risk_categories = [
        ConceptModel.model_validate(dict(item, kind="RiskCategory"))
        for item in _normalise_entity_list(entities_raw.get("risk_categories", []), name_field="name")
    ]
    topic_groups = [
        ConceptModel.model_validate(dict(item, kind="TopicGroup"))
        for item in _normalise_entity_list(entities_raw.get("topic_groups", []), name_field="name")
    ]
    topics = [
        TopicModel.model_validate(item)
        for item in _normalise_entity_list(entities_raw.get("topics", []), name_field="name")
    ]
    commitments = [
        CommitmentModel.model_validate(item)
        for item in _normalise_entity_list(
            entities_raw.get("commitments", []),
            id_fallbacks=("id", "text"),
            name_field="text",
        )
    ]

    relationships_raw = preview.get("relationships", []) if isinstance(preview, dict) else []
    relationships = [
        RelationshipModel.model_validate(rel)
        for rel in relationships_raw
        if isinstance(rel, dict) and rel.get("src") and rel.get("dst") and rel.get("rel")
    ]

    entities = EntitiesModel(
        stakeholder_types=stakeholder_types,
        risk_categories=risk_categories,
        topic_groups=topic_groups,
        orgs=orgs,
        persons=persons,
        projects=projects,
        contracts=contracts,
        topics=topics,
        commitments=commitments,
    )

    return InteractionBundle(interaction=interaction, entities=entities, relationships=relationships)
