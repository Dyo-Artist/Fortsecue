from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field
from logos.graphio.neo4j_client import get_client
from logos.graphio.schema_store import SchemaStore
from logos.graphio.types import (
    GraphNode,
    GraphRelationship,
    _ensure_valid_label,
    _ensure_valid_rel_type,
)
from logos.models.bundles import UpsertBundle

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
    user: str | None,
) -> None:
    concept_id = node.concept_id
    if not concept_id:
        return
    concept_label = schema_store.get_schema_convention("concept_label", "Concept")
    instance_rel = schema_store.get_schema_convention("instance_of_relationship", "INSTANCE_OF")
    resolved_kind = concept_kind or "DynamicConcept"
    concept_node = GraphNode(
        id=concept_id,
        label=concept_label,
        properties={
            "name": concept_id,
            "kind": resolved_kind,
        },
        source_uri=node.source_uri,
    )
    upsert_node(tx, concept_node, now, schema_store=schema_store, user=user)
    rel = GraphRelationship(
        src=node.id,
        dst=concept_id,
        rel_type=instance_rel,
        src_label=node.label,
        dst_label=concept_label,
        source_uri=node.source_uri,
    )
    upsert_relationship(tx, rel, rel.source_uri or "", now, schema_store=schema_store, user=user)


def _resolve_concept_kind(node: GraphNode, schema_store: SchemaStore) -> str | None:
    if node.concept_kind:
        return node.concept_kind
    label = _ensure_valid_label(node.label)
    entry = schema_store.node_types.get(label)
    if entry and entry.concept_kind:
        return entry.concept_kind
    return None


def upsert_node(
    tx,
    node: GraphNode,
    now: datetime,
    *,
    schema_store: SchemaStore = SCHEMA_STORE,
    user: str | None = "system",
) -> None:
    label = _ensure_valid_label(node.label)
    resolved_concept_kind = _resolve_concept_kind(node, schema_store)
    props = _clean_properties(node.properties)
    schema_props = set(props.keys()) | {"source_uri"}
    if not node.source_uri:
        raise ValueError(f"GraphNode {node.id} is missing a source_uri for provenance")
    schema_store.record_node_type(label, schema_props, concept_kind=resolved_concept_kind, now=now)

    cypher = (
        f"MERGE (n:{label} {{id: $id}}) "
        "SET n += $props "
        "SET n.source_uri = coalesce(n.source_uri, $source_uri), "
        "n.updated_at = datetime($now), n.last_seen_at = datetime($now), "
        "n.created_at = coalesce(n.created_at, datetime($now)), n.first_seen_at = coalesce(n.first_seen_at, datetime($now))"
    )
    if user:
        cypher = f"{cypher}, n.created_by = coalesce(n.created_by, $user), n.updated_by = $user"
    tx.run(
        cypher,
        {
            "id": node.id,
            "props": props,
            "source_uri": node.source_uri,
            "now": _dt_param(now),
            "user": user,
        },
    )
    if node.concept_id:
        _merge_concept(tx, node, resolved_concept_kind, now, schema_store=schema_store, user=user)


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
    user: str | None = "system",
) -> None:
    rel_type = _ensure_valid_rel_type(rel.rel_type)
    if not source_uri:
        raise ValueError(f"Relationship {rel.src}->{rel.rel_type}->{rel.dst} is missing a source_uri for provenance")
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
    if user:
        cypher = f"{cypher}, r.created_by = coalesce(r.created_by, $user), r.updated_by = $user"
    params: dict[str, Any] = {
        "src": rel.src,
        "dst": rel.dst,
        "props": props,
        "source_uri": source_uri,
        "now": _dt_param(now),
        "user": user,
    }
    tx.run(cypher, params)


def upsert_interaction_bundle(
    tx,
    bundle: InteractionBundle,
    now: datetime,
    *,
    schema_store: SchemaStore = SCHEMA_STORE,
    user: str | None = "system",
) -> None:
    source_uri = bundle.interaction.source_uri or f"interaction://{bundle.interaction.id}"
    bundle.interaction.source_uri = source_uri
    for node in bundle.all_nodes:
        node.source_uri = node.source_uri or source_uri
        upsert_node(tx, node, now, schema_store=schema_store, user=user)

    for rel in bundle.relationships:
        rel.source_uri = rel.source_uri or source_uri
        upsert_relationship(tx, rel, rel.source_uri, now, schema_store=schema_store, user=user)


def _resolve_bundle_user(bundle: UpsertBundle, user: str | None) -> str | None:
    if user:
        return user
    return bundle.meta.created_by or "system"


def _commit_bundle_tx(
    tx,
    bundle: UpsertBundle,
    now: datetime,
    *,
    user: str | None,
    schema_store: SchemaStore,
) -> None:
    source_uri = bundle.meta.source_uri or f"interaction://{bundle.meta.interaction_id}"
    for node_data in bundle.nodes:
        node = GraphNode.model_validate(node_data)
        node.source_uri = node.source_uri or source_uri
        upsert_node(tx, node, now, schema_store=schema_store, user=user)
    for rel_data in bundle.relationships:
        rel = GraphRelationship.model_validate(rel_data)
        rel_source = rel.source_uri or rel_data.get("source_uri") or source_uri
        upsert_relationship(tx, rel, rel_source, now, schema_store=schema_store, user=user)
    for line in bundle.dialectical_lines:
        rel = GraphRelationship.model_validate(line)
        rel_source = rel.source_uri or source_uri
        upsert_relationship(tx, rel, rel_source, now, schema_store=schema_store, user=user)


def commit_upsert_bundle(bundle: UpsertBundle, user: str | None = "system") -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    schema_store = SCHEMA_STORE
    resolved_user = _resolve_bundle_user(bundle, user)
    client = get_client()

    def _tx(tx):
        _commit_bundle_tx(tx, bundle, now, user=resolved_user, schema_store=schema_store)

    client.run_in_tx(_tx)
    return {
        "interaction_id": bundle.meta.interaction_id,
        "nodes_committed": len(bundle.nodes),
        "relationships_committed": len(bundle.relationships),
        "dialectical_lines_committed": len(bundle.dialectical_lines),
    }


__all__ = [
    "GraphNode",
    "GraphRelationship",
    "InteractionBundle",
    "upsert_node",
    "upsert_relationship",
    "upsert_interaction_bundle",
    "commit_upsert_bundle",
    "SCHEMA_STORE",
]
