import json
import pathlib
import sys
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from logos.graphio.types import GraphRelationship
from logos.models.bundles import (
    EntityMention,
    InteractionMeta,
    InteractionSnapshot,
    ParsedContentBundle,
    PreviewBundle,
    PreviewEntity,
    RawInputBundle,
    ResolvedBundle,
)


def _meta(source_uri: str = "") -> InteractionMeta:
    return InteractionMeta(
        interaction_id="i-1",
        interaction_type="note",
        interaction_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        source_uri=source_uri,
        source_type="text",
        created_by="tester",
        received_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


def test_interaction_meta_validation():
    meta = _meta("file://example")
    assert meta.source_type == "text"

    with pytest.raises(ValidationError):
        InteractionMeta(
            interaction_id="i-2",
            interaction_type="doc",
            interaction_at=datetime.now(timezone.utc),
            source_type="video",  # not in allowed literal set
        )


def test_preview_bundle_round_trip_json():
    preview = PreviewBundle(
        meta=_meta("file://doc"),
        interaction=InteractionSnapshot(summary="hello", sentiment=0.5),
        entities={
            "persons": [PreviewEntity(temp_id="p1", canonical_id="c1", confidence=0.9)],
            "orgs": [PreviewEntity(temp_id="o1", is_new=True)],
        },
    )

    encoded = preview.model_dump_json()
    decoded = PreviewBundle.model_validate_json(encoded)
    assert decoded.ready is True
    assert decoded.interaction.summary == "hello"
    assert decoded.entities["persons"][0].canonical_id == "c1"

    # ensure plain JSON string can rehydrate
    payload = json.loads(encoded)
    reconstructed = PreviewBundle.model_validate(payload)
    assert reconstructed.meta.source_uri == "file://doc"


def test_optional_fields_on_parsed_content():
    raw = RawInputBundle(meta=_meta(), raw_text="Sample text")
    parsed = ParsedContentBundle(meta=raw.meta, text=raw.text)
    assert parsed.language is None
    assert parsed.structure is None
    assert parsed.tokens == []
    assert parsed.metadata == {}

    parsed_json = parsed.model_dump_json()
    parsed_round_trip = ParsedContentBundle.model_validate_json(parsed_json)
    assert parsed_round_trip.text == "Sample text"


def test_entity_action_literal():
    entity = EntityMention(temp_id="t1", action="create")
    assert entity.action == "create"
    with pytest.raises(ValidationError):
        EntityMention(temp_id="t2", action="unknown")


def test_resolved_bundle_accepts_dialectical_lines():
    bundle = ResolvedBundle(
        meta=_meta("file://dialectic"),
        dialectical_lines=[GraphRelationship(src="a1", dst="b1", rel="RELATED_TO")],
    )

    assert bundle.dialectical_lines[0].rel == "RELATED_TO"
