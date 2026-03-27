from logos.information.converters import belief_candidates_from_preview_bundle
from logos.models.bundles import InteractionMeta, PreviewBundle, PreviewEntity, Relationship


def _build_preview_bundle() -> PreviewBundle:
    return PreviewBundle(
        meta=InteractionMeta(
            interaction_id="i1",
            interaction_type="meeting",
            source_uri="file:///notes/meeting.md",
            source_type="doc",
        ),
        interaction={"summary": "Alice works for Acme"},
        entities={
            "persons": [PreviewEntity(id="p1", name="Alice")],
            "orgs": [PreviewEntity(id="o1", name="Acme")],
        },
        relationships=[
            Relationship(
                src="p1",
                dst="o1",
                rel="WORKS_FOR",
                confidence=0.82,
                properties={"source_uri": "file:///notes/meeting.md"},
            )
        ],
    )


def test_conversion_from_preview_is_deterministic():
    preview = _build_preview_bundle()

    first = belief_candidates_from_preview_bundle(preview, correlation_id="corr-1")
    second = belief_candidates_from_preview_bundle(preview, correlation_id="corr-1")

    assert len(first.beliefs) == 1
    assert first.beliefs[0].id == second.beliefs[0].id
    assert first.beliefs[0].statement.subject.ref == "Person:p1"
    assert first.beliefs[0].statement.object.ref == "Org:o1"


def test_conversion_preserves_source_uri_provenance():
    preview = _build_preview_bundle()

    result = belief_candidates_from_preview_bundle(preview, correlation_id="corr-42")

    assert result.beliefs[0].provenance.source_uri == "file:///notes/meeting.md"
    assert result.beliefs[0].provenance.supporting_event_ids == ["corr-42"]
    assert result.evidence[0].source_uri == "file:///notes/meeting.md"
