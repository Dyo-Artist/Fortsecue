from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence

import yaml

from logos.core.pipeline_executor import PipelineContext, STAGE_REGISTRY
from logos.graphio.neo4j_client import get_client
from logos.graphio.upsert import GraphNode, GraphRelationship, SCHEMA_STORE, upsert_node, upsert_relationship
from logos.knowledgebase.store import KnowledgebaseStore

logger = logging.getLogger(__name__)


def _trace(context: Dict[str, Any], stage_name: str) -> None:
    trace: list[str] = context.setdefault("trace", [])  # type: ignore[assignment]
    trace.append(stage_name)


def _singularise(word: str) -> str:
    if word.endswith("ies") and len(word) > 3:
        return f"{word[:-3]}y"
    if word.endswith("ses") and len(word) > 3:
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _concept_kind_from_key(key: str) -> str:
    words = [segment for segment in key.replace("-", "_").split("_") if segment]
    if not words:
        return "Concept"
    words[-1] = _singularise(words[-1])
    return "".join(word.capitalize() for word in words)


def _extract_parent_ids(entry: Mapping[str, Any], extra_keys: Sequence[str]) -> list[str]:
    parent_ids: list[str] = []
    for key in extra_keys:
        value = entry.get(key)
        if isinstance(value, list):
            parent_ids.extend(str(item) for item in value if item)
        elif value:
            parent_ids.append(str(value))
    return parent_ids


def _load_yaml(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}
    except yaml.YAMLError as exc:  # pragma: no cover - defensive guard
        logger.warning("Failed to parse concepts file %s: %s", path, exc)
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _build_concept_nodes(
    concepts_dir: Path,
    concept_label: str,
    parent_relationship: str,
) -> tuple[list[GraphNode], list[GraphRelationship], list[str]]:
    concept_nodes: list[GraphNode] = []
    hierarchy_rels: list[GraphRelationship] = []
    child_ids: list[str] = []

    if not concepts_dir.exists():
        logger.warning("Concepts directory not found at %s", concepts_dir)
        return concept_nodes, hierarchy_rels, child_ids

    for path in sorted(concepts_dir.glob("*.yml")):
        payload = _load_yaml(path)
        for key, entries in payload.items():
            if key == "metadata":
                continue
            if not isinstance(entries, list):
                continue

            kind_from_key = _concept_kind_from_key(str(key))
            for entry in entries:
                if not isinstance(entry, Mapping):
                    continue

                concept_id = entry.get("id")
                if not concept_id:
                    logger.debug("Skipping concept entry without id in %s", path)
                    continue

                concept_id_str = str(concept_id)
                concept_kind = str(entry.get("kind") or kind_from_key)
                name = entry.get("name") or concept_id_str

                properties = dict(entry)
                properties.pop("id", None)
                properties.pop("parent_id", None)
                properties.pop("parent_ids", None)
                properties.pop("parents", None)
                properties.pop("parent", None)
                properties.pop("form_id", None)
                properties["name"] = name
                properties["kind"] = concept_kind

                concept_nodes.append(
                    GraphNode(
                        id=concept_id_str,
                        label=concept_label,
                        properties=properties,
                        source_uri=str(path),
                    )
                )

                parent_ids = _extract_parent_ids(
                    entry,
                    ["parent_id", "parent_ids", "parents", "parent", "form_id"],
                )
                for parent_id in parent_ids:
                    hierarchy_rels.append(
                        GraphRelationship(
                            src=parent_id,
                            dst=concept_id_str,
                            rel_type=parent_relationship,
                            src_label=concept_label,
                            dst_label=concept_label,
                            source_uri=str(path),
                        )
                    )
                    child_ids.append(concept_id_str)

    return concept_nodes, hierarchy_rels, child_ids


@STAGE_REGISTRY.register("concepts.update")
def stage_concept_update(bundle: Any, ctx: PipelineContext) -> Dict[str, Any]:
    context = ctx.to_mapping()
    _trace(context, "concepts.update")

    knowledgebase_path = context.get("knowledgebase_path")
    kb_store = KnowledgebaseStore(base_path=knowledgebase_path) if knowledgebase_path else KnowledgebaseStore()
    concepts_dir = kb_store.base_path / "concepts"

    schema_store = context.get("schema_store", SCHEMA_STORE)
    concept_label = schema_store.get_schema_convention("concept_label", "Concept") or "Concept"
    parent_relationship = (
        context.get("parent_of_relationship")
        or schema_store.get_schema_convention("parent_of_relationship", "PARENT_OF")
        or "PARENT_OF"
    )

    concept_nodes, hierarchy_rels, child_ids = _build_concept_nodes(
        concepts_dir, concept_label, parent_relationship
    )

    if not concept_nodes:
        return {"status": "no_concepts_found", "concept_count": 0, "relationship_count": 0}

    client_factory = context.get("graph_client_factory") or get_client
    commit_time = context.get("commit_time") or datetime.now(timezone.utc)
    actor = context.get("actor") or context.get("user") or "system"
    rebuild_hierarchy = bool(context.get("rebuild_hierarchy", True))

    client = client_factory()

    def _tx(tx) -> None:
        for node in concept_nodes:
            upsert_node(tx, node, commit_time, schema_store=schema_store, user=actor)

        if rebuild_hierarchy and child_ids:
            tx.run(
                f"MATCH (parent:{concept_label})-[r:{parent_relationship}]->(child:{concept_label}) "
                "WHERE child.id IN $child_ids DELETE r",
                {"child_ids": sorted(set(child_ids))},
            )

        for rel in hierarchy_rels:
            upsert_relationship(
                tx,
                rel,
                rel.source_uri or "",
                commit_time,
                schema_store=schema_store,
                user=actor,
            )

    client.run_in_tx(_tx)

    return {
        "status": "concepts_updated",
        "concept_count": len(concept_nodes),
        "relationship_count": len(hierarchy_rels),
    }


__all__ = ["stage_concept_update"]
