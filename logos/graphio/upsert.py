from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator

from logos.graphio.schema_store import SchemaStore

LABEL_PATTERN = re.compile(r"^[A-Z][A-Za-z0-9_]*$")
REL_TYPE_PATTERN = re.compile(r"^[A-Z0-9_]+$")

SCHEMA_STORE = SchemaStore()


def _dt_param(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _clean_properties(properties: Mapping[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in properties.items():
        if key == "id":
            continue
        if value is None:
            continue
        if isinstance(value, datetime):
            cleaned[key] = _dt_param(value)
        else:
            cleaned[key] = value
    return cleaned


def _ensure_valid_label(label: str) -> str:
    candidate = label[0].upper() + label[1:] if label else label
    if not LABEL_PATTERN.match(candidate):
        raise ValueError(f"Invalid node label: {label}")
    return candidate


def _ensure_valid_rel_type(rel_type: str) -> str:
    if not REL_TYPE_PATTERN.match(rel_type):
        raise ValueError(f"Invalid relationship type: {rel_type}")
    return rel_type


class GraphNode(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    label: str
    properties: dict[str, Any] = Field(default_factory=dict)
    concept_id: str | None = None
    concept_kind: str | None = None
    source_uri: str | None = None

    @field_validator("label")
    @classmethod
    def _validate_label(cls, value: str) -> str:
        return _ensure_valid_label(value)


class GraphRelationship(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    src: str
    dst: str
    rel_type: str = Field(alias="rel")
    src_label: str | None = None
    dst_label: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    source_uri: str | None = None

    @field_validator("rel_type")
    @classmethod
    def _validate_rel(cls, value: str) -> str:
        return _ensure_valid_rel_type(value.upper())

    @field_validator("src_label", "dst_label")
    @classmethod
    def _validate_optional_labels(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _ensure_valid_label(value)

    @property
    def rel(self) -> str:
        """Backwards-compatible access to the relationship type."""

        return self.rel_type


class InteractionBundle(BaseModel):
    model_config = ConfigDict(extra="ignore")

    interaction: GraphNode
    nodes: list[GraphNode] = Field(default_factory=list)
    relationships: list[GraphRelationship] = Field(default_factory=list)

    @property
    def all_nodes(self) -> list[GraphNode]:
        return [self.interaction, *self.nodes]


def _merge_concept(
    tx,
    node: GraphNode,
    concept_kind: str | None,
    now: datetime,
    *,
    schema_store: SchemaStore,
) -> None:
    concept_id = node.concept_id
    if not concept_id:
        return
    concept_node = GraphNode(
        id=concept_id,
        label="Concept",
        properties={
            "name": concept_id,
            "kind": concept_kind or node.concept_kind or "DynamicConcept",
        },
        source_uri=node.source_uri,
    )
    upsert_node(tx, concept_node, now, schema_store=schema_store)
    rel = GraphRelationship(
        src=node.id,
        dst=concept_id,
        rel_type="INSTANCE_OF",
        src_label=node.label,
        dst_label="Concept",
        source_uri=node.source_uri,
    )
    upsert_relationship(tx, rel, rel.source_uri or "", now, schema_store=schema_store)


def upsert_node(tx, node: GraphNode, now: datetime, *, schema_store: SchemaStore = SCHEMA_STORE) -> None:
    label = _ensure_valid_label(node.label)
    props = _clean_properties(node.properties)
    schema_props = set(props.keys()) | {"source_uri"}
    schema_store.record_node_type(label, schema_props, concept_kind=node.concept_kind, now=now)

    cypher = (
        f"MERGE (n:{label} {{id: $id}}) "
        "SET n += $props "
        "SET n.source_uri = coalesce(n.source_uri, $source_uri), "
        "n.updated_at = datetime($now), n.last_seen_at = datetime($now), "
        "n.created_at = coalesce(n.created_at, datetime($now)), n.first_seen_at = coalesce(n.first_seen_at, datetime($now))"
    )
    tx.run(
        cypher,
        {
            "id": node.id,
            "props": props,
            "source_uri": node.source_uri,
            "now": _dt_param(now),
        },
    )
    _merge_concept(tx, node, node.concept_kind, now, schema_store=schema_store)


def _labelled_node(var: str, label: str | None) -> str:
    if label:
        safe_label = _ensure_valid_label(label)
        return f"({var}:{safe_label} {{id: ${var}}})"
    return f"({var} {{id: ${var}}})"


def upsert_relationship(
    tx,
    rel: GraphRelationship,
    source_uri: str,
    now: datetime,
    *,
    schema_store: SchemaStore = SCHEMA_STORE,
) -> None:
    rel_type = _ensure_valid_rel_type(rel.rel_type)
    props = _clean_properties(rel.properties)
    schema_store.record_relationship_type(rel_type, set(props.keys()) | {"source_uri"}, now=now)

    src = _labelled_node("src", rel.src_label)
    dst = _labelled_node("dst", rel.dst_label)
    cypher = (
        f"MATCH {src} MATCH {dst} "
        f"MERGE (src)-[r:{rel_type}]->(dst) "
        "SET r += $props "
        "SET r.source_uri = coalesce(r.source_uri, $source_uri), "
        "r.updated_at = datetime($now), r.last_seen_at = datetime($now), "
        "r.created_at = coalesce(r.created_at, datetime($now)), r.first_seen_at = coalesce(r.first_seen_at, datetime($now))"
    )
    params: dict[str, Any] = {
        "src": rel.src,
        "dst": rel.dst,
        "props": props,
        "source_uri": source_uri,
        "now": _dt_param(now),
    }
    tx.run(cypher, params)


def upsert_interaction_bundle(
    tx,
    bundle: InteractionBundle,
    now: datetime,
    *,
    schema_store: SchemaStore = SCHEMA_STORE,
) -> None:
    source_uri = bundle.interaction.source_uri
    for node in bundle.all_nodes:
        node.source_uri = node.source_uri or source_uri
        upsert_node(tx, node, now, schema_store=schema_store)

    for rel in bundle.relationships:
        rel.source_uri = rel.source_uri or source_uri
        upsert_relationship(tx, rel, rel.source_uri, now, schema_store=schema_store)


__all__ = [
    "GraphNode",
    "GraphRelationship",
    "InteractionBundle",
    "upsert_node",
    "upsert_relationship",
    "upsert_interaction_bundle",
    "SCHEMA_STORE",
]
