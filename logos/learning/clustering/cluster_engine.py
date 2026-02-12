from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from logos.graphio.neo4j_client import Neo4jClient, get_client
from logos.graphio.schema_store import SchemaStore


@dataclass(frozen=True)
class ProposedConcept:
    concept_id: str
    status: str
    parent_form: str
    provenance: Mapping[str, Any]


class ClusterEngine:
    """Governed cluster-to-concept proposal engine.

    Clusters may suggest candidate concept nodes, but concepts remain proposed
    unless explicitly promoted by a manual trigger.
    """

    def __init__(
        self,
        *,
        client: Neo4jClient | None = None,
        schema_store: SchemaStore | None = None,
    ) -> None:
        self._client = client or get_client()
        self._schema_store = schema_store or SchemaStore(mutable=True)

    def propose_concept_from_cluster(
        self,
        *,
        cluster_id: str,
        parent_form: str,
        particular_ids: Sequence[str],
        algorithm: str,
        created_at: datetime | None = None,
        provenance: Mapping[str, Any] | None = None,
    ) -> ProposedConcept:
        now = created_at or datetime.now(timezone.utc)
        created_at_iso = _to_iso(now)

        concept_label = self._schema_store.get_schema_convention("concept_label", "Concept") or "Concept"
        particular_label = self._schema_store.get_schema_convention("particular_label", "Particular") or "Particular"
        candidate_rel = (
            self._schema_store.get_schema_convention("candidate_instance_of_relationship", "CANDIDATE_INSTANCE_OF")
            or "CANDIDATE_INSTANCE_OF"
        )

        concept_id = _proposed_concept_id(cluster_id=cluster_id, parent_form=parent_form, particular_ids=particular_ids)
        concept_provenance: dict[str, Any] = {
            "source": "cluster_engine",
            "cluster_id": cluster_id,
            "algorithm": algorithm,
            "generated_at": created_at_iso,
            "term_count": len(particular_ids),
            "review_required": True,
        }
        if provenance:
            concept_provenance.update(dict(provenance))

        self._client.run(
            (
                f"MERGE (c:{concept_label} {{id: $id}}) "
                "ON CREATE SET c.created_at = datetime($created_at) "
                "SET c.status = 'proposed', c.parent_form = $parent_form, "
                "c.provenance = $provenance, c.updated_at = datetime($created_at)"
            ),
            {
                "id": concept_id,
                "created_at": created_at_iso,
                "parent_form": parent_form,
                "provenance": concept_provenance,
            },
        )

        for particular_id in sorted(set(particular_ids)):
            self._client.run(
                (
                    f"MATCH (p:{particular_label} {{id: $particular_id}}) "
                    f"MATCH (c:{concept_label} {{id: $concept_id}}) "
                    f"MERGE (p)-[r:{candidate_rel}]->(c) "
                    "SET r.algorithm = $algorithm, r.created_at = datetime($created_at), r.provenance = $provenance"
                ),
                {
                    "particular_id": particular_id,
                    "concept_id": concept_id,
                    "algorithm": algorithm,
                    "created_at": created_at_iso,
                    "provenance": concept_provenance,
                },
            )

        self._schema_store.record_relationship_type(
            candidate_rel,
            {"algorithm", "created_at", "provenance"},
            now=now,
        )

        return ProposedConcept(
            concept_id=concept_id,
            status="proposed",
            parent_form=parent_form,
            provenance=concept_provenance,
        )

    def promote_proposed_concept(self, *, concept_id: str, manual_trigger: bool, promoted_by: str) -> bool:
        """Promote a proposed concept only when explicitly manually triggered."""
        if not manual_trigger:
            return False

        concept_label = self._schema_store.get_schema_convention("concept_label", "Concept") or "Concept"
        now_iso = _to_iso(datetime.now(timezone.utc))
        self._client.run(
            (
                f"MATCH (c:{concept_label} {{id: $concept_id}}) "
                "WHERE c.status = 'proposed' "
                "SET c.status = 'canonical', c.promoted_at = datetime($promoted_at), c.promoted_by = $promoted_by"
            ),
            {
                "concept_id": concept_id,
                "promoted_at": now_iso,
                "promoted_by": promoted_by,
            },
        )
        return True


def _proposed_concept_id(*, cluster_id: str, parent_form: str, particular_ids: Sequence[str]) -> str:
    material = f"{cluster_id}|{parent_form}|{'|'.join(sorted(set(particular_ids)))}"
    digest = hashlib.sha1(material.encode("utf-8")).hexdigest()[:16]
    return f"proposed_concept_{digest}"


def _to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


__all__ = ["ClusterEngine", "ProposedConcept"]
