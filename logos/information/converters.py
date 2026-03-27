from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from logos.graphio.upsert import InteractionBundle
from logos.graphio.types import GraphRelationship
from logos.models.bundles import PreviewBundle, Relationship

from .models import (
    Belief,
    BeliefConversionResult,
    BeliefStatement,
    BeliefTerm,
    Evidence,
    Polarity,
    Provenance,
)


def _stable_belief_id(statement: BeliefStatement, polarity: Polarity = Polarity.UNKNOWN) -> str:
    payload = {
        "subject": statement.subject.ref,
        "predicate": statement.predicate,
        "object": statement.object.ref,
        "polarity": polarity.value,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return f"belief_{digest[:16]}"


def _labelled_ref(label: str | None, identifier: str) -> str:
    resolved_label = (label or "Entity").strip() or "Entity"
    return f"{resolved_label}:{identifier}"


def _relationship_confidence(rel: GraphRelationship | Relationship) -> float:
    props = getattr(rel, "properties", {}) or {}
    confidence = props.get("confidence")
    if confidence is None:
        confidence = getattr(rel, "confidence", None)
    try:
        return float(confidence) if confidence is not None else 0.5
    except (TypeError, ValueError):
        return 0.5


def _infer_preview_labels(preview: PreviewBundle) -> dict[str, str]:
    labels: dict[str, str] = {}
    for key, entries in preview.entities.items():
        label = key[:-1] if key.endswith("s") else key
        for entry in entries:
            candidate_id = entry.id or entry.canonical_id or entry.temp_id or entry.name
            if candidate_id:
                labels[str(candidate_id)] = label.capitalize()
    return labels


def _provenance(
    *,
    source_uri: str | None,
    source_type: str | None = None,
    correlation_id: str | None = None,
) -> Provenance:
    return Provenance(
        source_uri=source_uri,
        source_type=source_type,
        supporting_event_ids=[correlation_id] if correlation_id else [],
        pipeline_id=correlation_id,
    )


def belief_candidates_from_interaction_bundle(
    bundle: InteractionBundle,
    *,
    correlation_id: str | None = None,
) -> BeliefConversionResult:
    """Convert interaction relationships into belief candidates + evidence."""

    node_labels = {node.id: node.label for node in bundle.all_nodes}
    beliefs: list[Belief] = []
    evidence_items: list[Evidence] = []

    for rel in bundle.relationships:
        src_label = rel.src_label or node_labels.get(rel.src)
        dst_label = rel.dst_label or node_labels.get(rel.dst)

        statement = BeliefStatement(
            subject=BeliefTerm(ref=_labelled_ref(src_label, rel.src), label=src_label),
            predicate=rel.rel,
            object=BeliefTerm(ref=_labelled_ref(dst_label, rel.dst), label=dst_label),
        )
        provenance = _provenance(source_uri=rel.source_uri or bundle.interaction.source_uri, correlation_id=correlation_id)
        confidence = _relationship_confidence(rel)
        belief = Belief(
            id=_stable_belief_id(statement),
            statement=statement,
            polarity=Polarity.UNKNOWN,
            confidence=confidence,
            provenance=provenance,
        )
        beliefs.append(belief)
        evidence_items.append(
            Evidence(
                id=f"evidence_{belief.id}",
                belief_id=belief.id,
                relation_type="supports",
                event_id=correlation_id,
                source_uri=provenance.source_uri,
                confidence=confidence,
            )
        )

    contradiction_markers = [
        {
            "type": "dialectical_contradiction",
            "src": line.src,
            "dst": line.dst,
            "rel": line.rel,
            "source_uri": line.source_uri or bundle.interaction.source_uri,
            "supporting_event_ids": [correlation_id] if correlation_id else [],
        }
        for line in bundle.dialectical_lines
    ]

    return BeliefConversionResult(beliefs=beliefs, evidence=evidence_items, contradiction_markers=contradiction_markers)


def belief_candidates_from_preview_bundle(
    bundle: PreviewBundle,
    *,
    correlation_id: str | None = None,
) -> BeliefConversionResult:
    """Convert preview relationships into belief candidates + evidence."""

    inferred_labels = _infer_preview_labels(bundle)
    source_uri = bundle.meta.source_uri
    beliefs: list[Belief] = []
    evidence_items: list[Evidence] = []

    for rel in bundle.relationships:
        rel_source_uri = rel.properties.get("source_uri") if isinstance(rel.properties, Mapping) else None
        statement = BeliefStatement(
            subject=BeliefTerm(ref=_labelled_ref(inferred_labels.get(rel.src), rel.src), label=inferred_labels.get(rel.src)),
            predicate=rel.rel,
            object=BeliefTerm(ref=_labelled_ref(inferred_labels.get(rel.dst), rel.dst), label=inferred_labels.get(rel.dst)),
        )
        provenance = _provenance(
            source_uri=rel_source_uri or source_uri,
            source_type=bundle.meta.source_type,
            correlation_id=correlation_id,
        )
        confidence = _relationship_confidence(rel)
        belief = Belief(
            id=_stable_belief_id(statement),
            statement=statement,
            polarity=Polarity.UNKNOWN,
            confidence=confidence,
            provenance=provenance,
        )
        beliefs.append(belief)
        evidence_items.append(
            Evidence(
                id=f"evidence_{belief.id}",
                belief_id=belief.id,
                relation_type="supports",
                event_id=correlation_id,
                source_uri=provenance.source_uri,
                confidence=confidence,
            )
        )

    contradiction_markers: list[dict[str, Any]] = []
    raw_lines = getattr(bundle, "dialectical_lines", None)
    if isinstance(raw_lines, list):
        for line in raw_lines:
            if isinstance(line, Mapping) and line.get("src") and line.get("dst"):
                contradiction_markers.append(
                    {
                        "type": "dialectical_contradiction",
                        "src": line.get("src"),
                        "dst": line.get("dst"),
                        "rel": line.get("rel") or line.get("rel_type") or "CONTRADICTS",
                        "source_uri": line.get("source_uri") or source_uri,
                        "supporting_event_ids": [correlation_id] if correlation_id else [],
                    }
                )

    return BeliefConversionResult(beliefs=beliefs, evidence=evidence_items, contradiction_markers=contradiction_markers)


__all__ = [
    "belief_candidates_from_interaction_bundle",
    "belief_candidates_from_preview_bundle",
]
