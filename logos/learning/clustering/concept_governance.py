from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from logos.graphio.neo4j_client import Neo4jClient, get_client
from logos.graphio.schema_store import SchemaStore


class ConceptPromotionError(Exception):
    """Raised when concept promotion violates ontology governance rules."""

    def __init__(self, *, code: str, message: str, concept_id: str) -> None:
        self.code = code
        self.concept_id = concept_id
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class PromotionResult:
    concept_id: str
    status: str
    converted_relationships: int
    provenance: Mapping[str, Any]


@dataclass(frozen=True)
class MergeResult:
    proposed_concept_id: str
    target_concept_id: str
    status: str
    repointed_relationships: int
    provenance: Mapping[str, Any]


@dataclass(frozen=True)
class RejectionResult:
    concept_id: str
    status: str
    provenance: Mapping[str, Any]


class ConceptPromotionOntologyGuard:
    """Guard that ensures concept promotion follows ontology governance."""

    def __init__(self, *, client: Neo4jClient, schema_store: SchemaStore) -> None:
        self._client = client
        self._schema_store = schema_store

    def assert_promotable(self, *, concept_id: str) -> None:
        concept_label = self._schema_store.get_schema_convention("concept_label", "Concept") or "Concept"
        rows = self._client.run(
            f"MATCH (c:{concept_label} {{id: $concept_id}}) RETURN c.status AS status",
            {"concept_id": concept_id},
        )
        if not rows:
            raise ConceptPromotionError(
                code="CONCEPT_NOT_FOUND",
                message=f"Concept '{concept_id}' was not found",
                concept_id=concept_id,
            )

        status = rows[0].get("status")
        if status != "proposed":
            raise ConceptPromotionError(
                code="CONCEPT_NOT_PROPOSED",
                message=f"Only proposed concepts can be promoted (current status: {status!r})",
                concept_id=concept_id,
            )


class ConceptGovernance:
    def __init__(
        self,
        *,
        client: Neo4jClient | None = None,
        schema_store: SchemaStore | None = None,
    ) -> None:
        self._client = client or get_client()
        self._schema_store = schema_store or SchemaStore(mutable=True)
        self._promotion_guard = ConceptPromotionOntologyGuard(client=self._client, schema_store=self._schema_store)

    def promote_concept(self, concept_id: str, *, promoted_by: str = "api") -> PromotionResult:
        self._promotion_guard.assert_promotable(concept_id=concept_id)

        concept_label = self._schema_store.get_schema_convention("concept_label", "Concept") or "Concept"
        particular_label = self._schema_store.get_schema_convention("particular_label", "Particular") or "Particular"
        candidate_rel = (
            self._schema_store.get_schema_convention("candidate_instance_of_relationship", "CANDIDATE_INSTANCE_OF")
            or "CANDIDATE_INSTANCE_OF"
        )
        instance_rel = self._schema_store.get_schema_convention("instance_of_relationship", "INSTANCE_OF") or "INSTANCE_OF"

        now = datetime.now(timezone.utc).isoformat()
        converted_rows = self._client.run(
            (
                f"MATCH (p:{particular_label})-[candidate:{candidate_rel}]->(c:{concept_label} {{id: $concept_id}}) "
                f"MERGE (p)-[inst:{instance_rel}]->(c) "
                "SET inst.algorithm = coalesce(inst.algorithm, candidate.algorithm), "
                "inst.created_at = coalesce(inst.created_at, candidate.created_at), "
                "inst.provenance = coalesce(inst.provenance, candidate.provenance), "
                "inst.promoted_at = datetime($promoted_at), "
                "inst.promotion_source = $promotion_source "
                "DELETE candidate "
                "RETURN count(inst) AS converted_count"
            ),
            {
                "concept_id": concept_id,
                "promoted_at": now,
                "promotion_source": "concept_governance.promote_concept",
            },
        )
        converted = int(converted_rows[0]["converted_count"]) if converted_rows else 0

        provenance = {
            "source": "concept_governance.promote_concept",
            "promoted_by": promoted_by,
            "promoted_at": now,
            "converted_candidate_instance_of": converted,
        }
        self._client.run(
            (
                f"MATCH (c:{concept_label} {{id: $concept_id}}) "
                "SET c.status = 'canonical', "
                "c.promoted_at = datetime($promoted_at), "
                "c.promoted_by = $promoted_by, "
                "c.promotion_provenance = $promotion_provenance"
            ),
            {
                "concept_id": concept_id,
                "promoted_at": now,
                "promoted_by": promoted_by,
                "promotion_provenance": provenance,
            },
        )

        self._schema_store.record_relationship_type(
            instance_rel,
            {"algorithm", "created_at", "provenance", "promoted_at", "promotion_source"},
            now=datetime.fromisoformat(now),
        )

        return PromotionResult(
            concept_id=concept_id,
            status="canonical",
            converted_relationships=converted,
            provenance=provenance,
        )

    def merge_proposed_concept(
        self,
        proposed_concept_id: str,
        target_concept_id: str,
        *,
        merged_by: str = "api",
    ) -> MergeResult:
        self._promotion_guard.assert_promotable(concept_id=proposed_concept_id)

        concept_label = self._schema_store.get_schema_convention("concept_label", "Concept") or "Concept"
        particular_label = self._schema_store.get_schema_convention("particular_label", "Particular") or "Particular"
        candidate_rel = (
            self._schema_store.get_schema_convention("candidate_instance_of_relationship", "CANDIDATE_INSTANCE_OF")
            or "CANDIDATE_INSTANCE_OF"
        )
        instance_rel = self._schema_store.get_schema_convention("instance_of_relationship", "INSTANCE_OF") or "INSTANCE_OF"
        now = datetime.now(timezone.utc).isoformat()

        target_rows = self._client.run(
            f"MATCH (c:{concept_label} {{id: $concept_id}}) RETURN c.id AS id",
            {"concept_id": target_concept_id},
        )
        if not target_rows:
            raise ConceptPromotionError(
                code="TARGET_CONCEPT_NOT_FOUND",
                message=f"Target concept '{target_concept_id}' was not found",
                concept_id=proposed_concept_id,
            )

        repointed_rows = self._client.run(
            (
                f"MATCH (p:{particular_label})-[candidate:{candidate_rel}]->(source:{concept_label} {{id: $source_concept_id}}) "
                f"MATCH (target:{concept_label} {{id: $target_concept_id}}) "
                f"MERGE (p)-[moved:{candidate_rel}]->(target) "
                "SET moved.algorithm = coalesce(moved.algorithm, candidate.algorithm), "
                "moved.created_at = coalesce(moved.created_at, candidate.created_at), "
                "moved.provenance = coalesce(moved.provenance, candidate.provenance), "
                "moved.repointed_at = datetime($repointed_at), "
                "moved.repoint_source = $repoint_source "
                "DELETE candidate "
                "RETURN count(moved) AS repointed_count"
            ),
            {
                "source_concept_id": proposed_concept_id,
                "target_concept_id": target_concept_id,
                "repointed_at": now,
                "repoint_source": "concept_governance.merge_proposed_concept",
            },
        )
        repointed = int(repointed_rows[0]["repointed_count"]) if repointed_rows else 0

        self._client.run(
            (
                f"MATCH (c:{concept_label} {{id: $source_concept_id}}) "
                "SET c.status = 'merged', "
                "c.merged_into = $target_concept_id, "
                "c.merged_at = datetime($merged_at), "
                "c.merged_by = $merged_by, "
                "c.merge_provenance = $merge_provenance"
            ),
            {
                "source_concept_id": proposed_concept_id,
                "target_concept_id": target_concept_id,
                "merged_at": now,
                "merged_by": merged_by,
                "merge_provenance": {
                    "source": "concept_governance.merge_proposed_concept",
                    "merged_by": merged_by,
                    "merged_at": now,
                    "target_concept_id": target_concept_id,
                    "repointed_candidate_instance_of": repointed,
                },
            },
        )

        self._schema_store.record_relationship_type(
            candidate_rel,
            {"algorithm", "created_at", "provenance", "repointed_at", "repoint_source"},
            now=datetime.fromisoformat(now),
        )
        self._schema_store.record_relationship_type(
            instance_rel,
            {"algorithm", "created_at", "provenance", "promoted_at", "promotion_source"},
            now=datetime.fromisoformat(now),
        )

        provenance = {
            "source": "concept_governance.merge_proposed_concept",
            "merged_by": merged_by,
            "merged_at": now,
            "target_concept_id": target_concept_id,
            "repointed_candidate_instance_of": repointed,
        }
        return MergeResult(
            proposed_concept_id=proposed_concept_id,
            target_concept_id=target_concept_id,
            status="merged",
            repointed_relationships=repointed,
            provenance=provenance,
        )

    def reject_proposed_concept(self, concept_id: str, *, rejected_by: str = "api", reason: str | None = None) -> RejectionResult:
        self._promotion_guard.assert_promotable(concept_id=concept_id)
        concept_label = self._schema_store.get_schema_convention("concept_label", "Concept") or "Concept"
        now = datetime.now(timezone.utc).isoformat()
        provenance = {
            "source": "concept_governance.reject_proposed_concept",
            "rejected_by": rejected_by,
            "rejected_at": now,
            "reason": reason or "manual_rejection",
        }
        self._client.run(
            (
                f"MATCH (c:{concept_label} {{id: $concept_id}}) "
                "SET c.status = 'rejected', "
                "c.rejected_at = datetime($rejected_at), "
                "c.rejected_by = $rejected_by, "
                "c.rejection_reason = $reason, "
                "c.rejection_provenance = $rejection_provenance"
            ),
            {
                "concept_id": concept_id,
                "rejected_at": now,
                "rejected_by": rejected_by,
                "reason": reason or "manual_rejection",
                "rejection_provenance": provenance,
            },
        )
        return RejectionResult(concept_id=concept_id, status="rejected", provenance=provenance)


def promote_concept(concept_id: str, *, promoted_by: str = "api") -> PromotionResult:
    governance = ConceptGovernance()
    return governance.promote_concept(concept_id, promoted_by=promoted_by)


def merge_proposed_concept(
    proposed_concept_id: str,
    target_concept_id: str,
    *,
    merged_by: str = "api",
) -> MergeResult:
    governance = ConceptGovernance()
    return governance.merge_proposed_concept(proposed_concept_id, target_concept_id, merged_by=merged_by)


def reject_proposed_concept(concept_id: str, *, rejected_by: str = "api", reason: str | None = None) -> RejectionResult:
    governance = ConceptGovernance()
    return governance.reject_proposed_concept(concept_id, rejected_by=rejected_by, reason=reason)


__all__ = [
    "ConceptGovernance",
    "ConceptPromotionError",
    "ConceptPromotionOntologyGuard",
    "PromotionResult",
    "MergeResult",
    "RejectionResult",
    "promote_concept",
    "merge_proposed_concept",
    "reject_proposed_concept",
]
