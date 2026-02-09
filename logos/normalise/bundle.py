from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence

import yaml

from logos.graphio.upsert import GraphNode, GraphRelationship, InteractionBundle

RELATIONSHIP_TYPES_PATH = (
    Path(__file__).resolve().parent.parent / "knowledgebase" / "schema" / "relationship_types.yml"
)


def _normalise_entity_list(
    entries: Iterable[Any],
    *,
    id_fallbacks: tuple[str, ...] = ("id",),
) -> list[dict[str, Any]]:
    normalised: list[dict[str, Any]] = []
    for entry in entries:
        if isinstance(entry, str):
            normalised.append({"id": entry})
            continue
        if isinstance(entry, dict):
            entity_id = next((entry.get(key) for key in id_fallbacks if entry.get(key)), None)
            if not entity_id:
                continue
            record = dict(entry)
            record["id"] = entity_id
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


_REASONING_REL_TYPES = {"RESULT_OF", "RELATED_TO", "INFLUENCES"}


def _normalise_rel_key(rel: str) -> str:
    return rel.replace("-", "_").replace(" ", "_").upper()


def _load_relationship_mappings(path: Path = RELATIONSHIP_TYPES_PATH) -> dict[str, str]:
    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}

    entries = data.get("relationship_types") if isinstance(data.get("relationship_types"), Mapping) else data
    mapping: dict[str, str] = {}
    if not isinstance(entries, Mapping):
        return mapping

    for rel_type, definition in entries.items():
        if not rel_type:
            continue
        canonical = _normalise_rel_key(str(rel_type))
        mapping[_normalise_rel_key(str(rel_type))] = canonical
        if isinstance(definition, Mapping):
            aliases = definition.get("aliases") if isinstance(definition.get("aliases"), (list, tuple, set)) else []
            for alias in aliases:
                if alias:
                    mapping[_normalise_rel_key(str(alias))] = canonical
    return mapping


_REL_TYPE_MAP = _load_relationship_mappings()


def _refresh_relationship_mappings(path: Path | None = None) -> dict[str, str]:
    global _REL_TYPE_MAP
    _REL_TYPE_MAP = _load_relationship_mappings(path or RELATIONSHIP_TYPES_PATH)
    return _REL_TYPE_MAP


def _canonical_rel_type(rel: str | None, mapping: Mapping[str, str] | None = None) -> str | None:
    if not rel:
        return None
    rel_map = mapping or _REL_TYPE_MAP
    normalised = _normalise_rel_key(str(rel))
    return rel_map.get(normalised, normalised)


def _build_reasoning_relationships(
    entries: Iterable[Mapping[str, Any]],
    rel_map: Mapping[str, str] | None = None,
) -> list[GraphRelationship]:
    """Convert extracted reasoning entries into GraphRelationship instances."""

    relationships: list[GraphRelationship] = []
    mapping = rel_map or _REL_TYPE_MAP
    allowed = set(mapping.values()) if mapping else _REASONING_REL_TYPES
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue

        rel = _canonical_rel_type(entry.get("relation") or entry.get("rel"), mapping)
        if not rel or (allowed and rel not in allowed):
            continue

        src = entry.get("source") or entry.get("src") or entry.get("from")
        dst = entry.get("target") or entry.get("dst") or entry.get("to")
        if not src or not dst:
            continue

        props: dict[str, Any] = {}
        if isinstance(entry.get("properties"), Mapping):
            props.update(entry["properties"])

        explanation = entry.get("explanation") or entry.get("why") or entry.get("because")
        if explanation:
            props.setdefault("explanation", explanation)

        relationships.append(
            GraphRelationship(
                src=str(src),
                dst=str(dst),
                rel=rel,
                src_label=entry.get("source_label") or entry.get("src_label"),
                dst_label=entry.get("target_label") or entry.get("dst_label"),
                properties=props,
            )
        )

    return relationships


INFERENCE_RULES_PATH = Path(__file__).resolve().parent.parent / "knowledgebase" / "schema" / "inference.yml"


def _load_inference_rules(path: Path = INFERENCE_RULES_PATH) -> Mapping[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    return data if isinstance(data, Mapping) else {}


def _to_pascal(text: str) -> str:
    return "".join(part.capitalize() for part in text.replace("-", "_").split("_") if part)


def _singularise(token: str) -> str:
    if token.endswith("ies"):
        return token[:-3] + "y"
    if token.endswith("s"):
        return token[:-1]
    return token


def _label_from_key(key: str) -> str:
    return _to_pascal(_singularise(key))


def _concept_kind_from_key(key: str) -> str:
    lower = key.lower()
    suffix_map = {
        "_types": "Type",
        "_categories": "Category",
        "_groups": "Group",
    }
    for suffix, descriptor in suffix_map.items():
        if lower.endswith(suffix):
            base = lower[: -len(suffix)]
            return f"{_to_pascal(base)}{descriptor}"
    return _to_pascal(lower)


def _build_nodes_from_entities(
    entities_raw: Mapping[str, Any],
    source_uri: str | None,
    inference_rules: Mapping[str, Any],
) -> tuple[list[GraphNode], list[GraphRelationship]]:
    nodes: list[GraphNode] = []
    relationships: list[GraphRelationship] = []
    concept_nodes: dict[str, GraphNode] = {}

    for key, entries in entities_raw.items():
        if not isinstance(entries, Sequence):
            continue
        is_concept_key = str(key).endswith(("types", "categories", "groups", "concepts"))
        label = "Concept" if is_concept_key else _label_from_key(str(key))
        concept_kind = _concept_kind_from_key(str(key)) if is_concept_key else None
        normalised_entries = _normalise_entity_list(entries, id_fallbacks=("id", "name", "text"))
        for entry in normalised_entries:
            entry_props = dict(entry)
            node_id = str(entry_props.pop("id"))
            if label == "Commitment" and "person_id" in entry_props and "owner_id" not in entry_props:
                entry_props["owner_id"] = entry_props.pop("person_id")
            if "name" not in entry_props:
                if "title" in entry_props:
                    entry_props["name"] = entry_props["title"]
                elif "text" in entry_props:
                    entry_props["name"] = entry_props["text"]
                else:
                    entry_props["name"] = node_id
            concept_id = entry_props.pop("concept_id", None) or entry_props.get("concept")
            if not is_concept_key and concept_id is None:
                concept_id = entry_props.get("type") or entry_props.get("category")
            node = GraphNode(
                id=node_id,
                label=label,
                properties=entry_props,
                concept_id=None if is_concept_key else (str(concept_id) if concept_id else None),
                concept_kind=concept_kind if not is_concept_key else entry_props.get("kind", concept_kind),
                source_uri=entry_props.get("source_uri") or source_uri,
            )
            nodes.append(node)

            if is_concept_key:
                continue

            if concept_id:
                concept_node_id = str(concept_id)
                concept_nodes.setdefault(
                    concept_node_id,
                    GraphNode(
                        id=concept_node_id,
                        label="Concept",
                        properties={"name": concept_node_id, "kind": concept_kind or _label_from_key(str(key))},
                        source_uri=entry_props.get("source_uri") or source_uri,
                    ),
                )
                relationships.append(
                    GraphRelationship(
                        src=node_id,
                        dst=concept_node_id,
                        rel="INSTANCE_OF",
                        src_label=node.label,
                        dst_label="Concept",
                        source_uri=entry_props.get("source_uri") or source_uri,
                    )
                )

    nodes.extend(concept_nodes.values())
    relationships.extend(_derive_relationships_from_properties(nodes, inference_rules, source_uri))
    return nodes, relationships


def _derive_relationships_from_properties(
    nodes: Sequence[GraphNode],
    rules: Mapping[str, Any],
    source_uri: str | None,
) -> list[GraphRelationship]:
    property_rules = rules.get("property_relationships") if isinstance(rules.get("property_relationships"), Mapping) else {}
    relationships: list[GraphRelationship] = []

    for node in nodes:
        for prop_key, rule in property_rules.items():
            if prop_key not in node.properties:
                continue
            if not isinstance(rule, Mapping):
                continue
            allowed_sources = rule.get("source_labels")
            if allowed_sources and node.label not in allowed_sources:
                continue
            rel_type_raw = rule.get("rel") or rule.get("type")
            target_label = rule.get("target_label")
            rel_type = _canonical_rel_type(rel_type_raw)
            if not rel_type or not target_label:
                continue
            raw_value = node.properties.get(prop_key)
            values = raw_value if isinstance(raw_value, (list, tuple, set)) else [raw_value]
            for value in values:
                if value is None:
                    continue
                relationships.append(
                    GraphRelationship(
                        src=node.id,
                        dst=str(value),
                        rel=str(rel_type),
                        src_label=node.label,
                        dst_label=str(target_label),
                        source_uri=node.source_uri or source_uri,
                    )
                )
    return relationships


def _normalise_relationship_entries(
    relationships: Iterable[Mapping[str, Any]],
    rel_map: Mapping[str, str] | None = None,
) -> list[Mapping[str, Any]]:
    mapping = rel_map or _REL_TYPE_MAP
    normalised: list[Mapping[str, Any]] = []
    for rel in relationships:
        if not isinstance(rel, Mapping):
            continue
        canonical_rel = _canonical_rel_type(rel.get("rel") or rel.get("type"), mapping)
        if not canonical_rel:
            continue
        updated = dict(rel)
        updated["rel"] = canonical_rel
        normalised.append(updated)
    return normalised


def build_interaction_bundle(interaction_id: str, preview: Dict[str, Any]) -> InteractionBundle:
    interaction_raw = preview.get("interaction", {}) if isinstance(preview, dict) else {}
    interaction = GraphNode(
        id=interaction_raw.get("id") or interaction_id,
        label=interaction_raw.get("label") or "Interaction",
        properties={
            "type": interaction_raw.get("type") or "",
            "at": _parse_datetime(interaction_raw.get("at")) or interaction_raw.get("at"),
            "sentiment": interaction_raw.get("sentiment"),
            "summary": interaction_raw.get("summary"),
        },
        concept_id=interaction_raw.get("type"),
        concept_kind="InteractionType",
        source_uri=interaction_raw.get("source_uri"),
    )

    entities_raw = preview.get("entities", {}) if isinstance(preview, dict) else {}
    inference_rules = _load_inference_rules()
    nodes, inferred_relationships = _build_nodes_from_entities(entities_raw, interaction.source_uri, inference_rules)

    relationships_raw = preview.get("relationships", []) if isinstance(preview, dict) else []
    normalised_relationships = _normalise_relationship_entries(relationships_raw)
    reasoning_relationships = _build_reasoning_relationships(
        preview.get("reasoning", []) if isinstance(preview, dict) else [], _REL_TYPE_MAP
    )
    relationships = [
        GraphRelationship.model_validate(rel)
        for rel in normalised_relationships
        if isinstance(rel, dict) and rel.get("src") and rel.get("dst") and rel.get("rel")
    ] + inferred_relationships + reasoning_relationships

    return InteractionBundle(interaction=interaction, nodes=nodes, relationships=relationships)


def build_agent_bundle(
    person_id: str,
    *,
    person_name: str | None = None,
    agent_id: str | None = None,
    agent_name: str | None = None,
    created_by: str | None = None,
    source_uri: str | None = None,
) -> tuple[GraphNode, GraphNode, GraphRelationship]:
    resolved_person_id = str(person_id)
    resolved_person_name = person_name or resolved_person_id
    resolved_agent_id = agent_id or f"agent_{resolved_person_id}"
    resolved_agent_name = agent_name or f"LOGOS Assistant for {resolved_person_name}"
    resolved_source = source_uri or "agent://init"
    resolved_creator = created_by or resolved_person_id

    agent = GraphNode(
        id=resolved_agent_id,
        label="Agent",
        properties={"name": resolved_agent_name, "created_by": resolved_creator},
        concept_kind="AgentProfile",
        source_uri=resolved_source,
    )
    person = GraphNode(
        id=resolved_person_id,
        label="Person",
        properties={"name": resolved_person_name},
        concept_kind="StakeholderType",
        source_uri=resolved_source,
    )
    assists_rel = GraphRelationship(
        src=resolved_agent_id,
        dst=resolved_person_id,
        rel="ASSISTS",
        src_label="Agent",
        dst_label="Person",
        source_uri=resolved_source,
    )
    return agent, person, assists_rel
