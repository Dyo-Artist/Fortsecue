import json

from logos.events.types import EventEnvelope


def test_event_envelope_json_schema_snapshot_stability() -> None:
    expected_schema = {
        "additionalProperties": True,
        "description": "Standard event envelope shared by event bus backends and APIs.",
        "properties": {
            "causation_id": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Causation Id",
            },
            "confidence": {
                "anyOf": [{"maximum": 1.0, "minimum": 0.0, "type": "number"}, {"type": "null"}],
                "default": None,
                "title": "Confidence",
            },
            "correlation_id": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Correlation Id",
            },
            "event_id": {"title": "Event Id", "type": "string"},
            "event_type": {"minLength": 1, "title": "Event Type", "type": "string"},
            "occurred_at": {"format": "date-time", "title": "Occurred At", "type": "string"},
            "payload": {"title": "Payload", "type": "object"},
            "producer": {"minLength": 1, "title": "Producer", "type": "string"},
            "provenance": {"title": "Provenance", "type": "object"},
            "schema_version": {"default": "1.0", "title": "Schema Version", "type": "string"},
        },
        "required": ["event_type", "producer"],
        "title": "EventEnvelope",
        "type": "object",
    }

    assert EventEnvelope.model_json_schema() == expected_schema


def test_event_envelope_schema_is_json_serializable() -> None:
    schema = EventEnvelope.model_json_schema()
    serialized = json.dumps(schema, sort_keys=True)

    assert "EventEnvelope" in serialized
