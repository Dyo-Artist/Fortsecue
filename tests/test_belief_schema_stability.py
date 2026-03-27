from pathlib import Path

from logos.contradictions.engine import load_contradiction_rules
from logos.information.models import Belief


def test_belief_json_schema_snapshot_stability() -> None:
    expected_schema = {
        "$defs": {
            "BeliefStatement": {
                "additionalProperties": True,
                "description": "Structured subject-predicate-object statement.",
                "properties": {
                    "object": {"$ref": "#/$defs/BeliefTerm"},
                    "predicate": {"title": "Predicate", "type": "string"},
                    "subject": {"$ref": "#/$defs/BeliefTerm"},
                },
                "required": ["subject", "predicate", "object"],
                "title": "BeliefStatement",
                "type": "object",
            },
            "BeliefStatus": {
                "enum": ["candidate", "supported", "contested", "rejected"],
                "title": "BeliefStatus",
                "type": "string",
            },
            "BeliefTerm": {
                "additionalProperties": True,
                "description": "Term in a belief statement.",
                "properties": {
                    "label": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "default": None,
                        "title": "Label",
                    },
                    "ref": {"title": "Ref", "type": "string"},
                    "value": {"anyOf": [{}, {"type": "null"}], "default": None, "title": "Value"},
                },
                "required": ["ref"],
                "title": "BeliefTerm",
                "type": "object",
            },
            "Polarity": {
                "enum": ["positive", "negative", "unknown"],
                "title": "Polarity",
                "type": "string",
            },
            "Provenance": {
                "additionalProperties": True,
                "description": "Source and traceability metadata shared by InformationObjects and Beliefs.",
                "properties": {
                    "extracted_at": {"format": "date-time", "title": "Extracted At", "type": "string"},
                    "metadata": {"title": "Metadata", "type": "object"},
                    "pipeline_id": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "default": None,
                        "title": "Pipeline Id",
                    },
                    "source_type": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "default": None,
                        "title": "Source Type",
                    },
                    "source_uri": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "default": None,
                        "title": "Source Uri",
                    },
                    "supporting_event_ids": {
                        "items": {"type": "string"},
                        "title": "Supporting Event Ids",
                        "type": "array",
                    },
                },
                "title": "Provenance",
                "type": "object",
            },
        },
        "additionalProperties": True,
        "description": "Hypothesis-level assertion with confidence and provenance.",
        "properties": {
            "confidence": {"default": 0.5, "title": "Confidence", "type": "number"},
            "id": {"title": "Id", "type": "string"},
            "metadata": {"title": "Metadata", "type": "object"},
            "polarity": {"$ref": "#/$defs/Polarity", "default": "unknown"},
            "provenance": {"$ref": "#/$defs/Provenance"},
            "statement": {"$ref": "#/$defs/BeliefStatement"},
            "status": {"$ref": "#/$defs/BeliefStatus", "default": "candidate"},
        },
        "required": ["id", "statement"],
        "title": "Belief",
        "type": "object",
    }

    assert Belief.model_json_schema() == expected_schema


def test_contradiction_rules_parsing_contract() -> None:
    rules = load_contradiction_rules(Path("logos/knowledgebase/rules/contradictions.yml"))

    assert any(item.predicate == "OWNS" and item.cardinality == 1 for item in rules.hard_constraints)
    assert any(item.predicate == "WORKS_WITH" for item in rules.soft_constraints)
    assert any(item.predicate == "OWNS" and item.overlap_conflict for item in rules.temporal_rules)
    assert any(item.get("predicate") == "STATE" for item in rules.paradox_allowlist)
