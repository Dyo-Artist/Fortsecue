from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Mapping

from logos.graphio.schema_store import SchemaStore
from logos.graphio.upsert import InteractionBundle

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OntologyViolation:
    code: str
    message: str
    node_id: str | None = None
    relationship: str | None = None


class OntologyIntegrityError(Exception):
    """Structured integrity error raised when ontology constraints are violated."""

    def __init__(
        self,
        *,
        violations: list[OntologyViolation],
        provenance: Mapping[str, Any],
    ) -> None:
        self.violations = violations
        self.provenance = dict(provenance)
        super().__init__(self._render_message())

    def _render_message(self) -> str:
        return "; ".join(f"{item.code}: {item.message}" for item in self.violations)

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": "ontology_integrity_error",
            "violations": [
                {
                    "code": item.code,
                    "message": item.message,
                    "node_id": item.node_id,
                    "relationship": item.relationship,
                }
                for item in self.violations
            ],
            "provenance": dict(self.provenance),
        }


class OntologyIntegrityGuard:
    """Enforce structural integrity constraints before graph upsert."""

    def __init__(self, *, schema_store: SchemaStore) -> None:
        self._schema_store = schema_store

    def validate(self, bundle: InteractionBundle, *, context: Mapping[str, Any] | None = None) -> None:
        context_data = dict(context or {})
        concept_label = self._schema_store.get_schema_convention("concept_label", "Concept") or "Concept"
        instance_rel = (
            self._schema_store.get_schema_convention("instance_of_relationship", "INSTANCE_OF") or "INSTANCE_OF"
        )
        particular_label = self._schema_store.get_schema_convention("particular_label", "Particular") or "Particular"
        form_kind = self._schema_store.get_schema_convention("form_concept_kind", "Form") or "Form"

        violations: list[OntologyViolation] = []
        nodes_by_id = {node.id: node for node in bundle.all_nodes}

        instance_links: dict[str, list[str]] = {}
        for rel in bundle.relationships:
            if rel.rel_type != instance_rel:
                continue
            instance_links.setdefault(rel.src, []).append(rel.dst)

        for node in bundle.all_nodes:
            if node.label == concept_label:
                status = node.properties.get("status")
                if status not in {"proposed", "canonical"}:
                    violations.append(
                        OntologyViolation(
                            code="INVALID_CONCEPT_STATUS",
                            node_id=node.id,
                            message=(
                                f"Concept proposal '{node.id}' must have status in {{'proposed', 'canonical'}}"
                            ),
                        )
                    )
                continue

            if node.label != particular_label:
                continue

            linked_concept_id = node.concept_id
            linked_by_rel = instance_links.get(node.id, [])
            has_concept_link = bool(linked_concept_id or linked_by_rel)
            if not has_concept_link:
                violations.append(
                    OntologyViolation(
                        code="PARTICULAR_MISSING_INSTANCE_OF",
                        node_id=node.id,
                        relationship=instance_rel,
                        message=f"Particular '{node.id}' must define an {instance_rel} link to a Concept",
                    )
                )
                violations.append(
                    OntologyViolation(
                        code="ORPHAN_PARTICULAR",
                        node_id=node.id,
                        message=f"Particular '{node.id}' cannot be committed as an orphan",
                    )
                )

            if node.concept_id and node.concept_kind == form_kind and node.concept_id not in nodes_by_id:
                violations.append(
                    OntologyViolation(
                        code="AUTOMATIC_FORM_CREATION_FORBIDDEN",
                        node_id=node.id,
                        message=(
                            f"Particular '{node.id}' references Form concept '{node.concept_id}' without an explicit "
                            "Concept proposal node"
                        ),
                    )
                )

        if not violations:
            return

        provenance = {
            "interaction_id": bundle.interaction.id,
            "interaction_source_uri": bundle.interaction.source_uri,
            "bundle_sources": sorted({node.source_uri for node in bundle.all_nodes if node.source_uri}),
            "context_source_uri": context_data.get("source_uri"),
        }
        logger.error(
            "ontology_integrity_violation",
            extra={
                "interaction_id": bundle.interaction.id,
                "violations": [item.__dict__ for item in violations],
                "provenance": provenance,
            },
        )
        raise OntologyIntegrityError(violations=violations, provenance=provenance)


__all__ = [
    "OntologyIntegrityError",
    "OntologyIntegrityGuard",
    "OntologyViolation",
]

