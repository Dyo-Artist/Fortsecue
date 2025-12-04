from datetime import datetime

from logos.normalise.bundle import build_interaction_bundle


def test_reasoning_relationships_are_built_from_preview():
    preview = {
        "interaction": {"id": "i_reason", "type": "note", "at": datetime(2024, 1, 1).isoformat()},
        "entities": {
            "persons": [{"id": "p1", "name": "Alice"}],
            "risks": [{"id": "risk1", "title": "Schedule slip"}],
            "issues": [{"id": "issue1", "title": "Budget overrun"}],
        },
        "relationships": [{"src": "i_reason", "dst": "p1", "rel": "MENTIONS"}],
        "reasoning": [
            {
                "source": "risk1",
                "target": "issue1",
                "relation": "result_of",
                "explanation": "Risk flows from budget concerns",
                "source_label": "Risk",
                "target_label": "Issue",
            },
            {
                "src": "p1",
                "dst": "p2",
                "rel": "influences",
                "because": "Team lead",  # alternate key should be captured
            },
        ],
    }

    bundle = build_interaction_bundle("i_reason", preview)

    result_rel = next(rel for rel in bundle.relationships if rel.rel == "RESULT_OF")
    influence_rel = next(rel for rel in bundle.relationships if rel.rel == "INFLUENCES")

    assert result_rel.src == "risk1"
    assert result_rel.dst == "issue1"
    assert result_rel.properties.get("explanation") == "Risk flows from budget concerns"
    assert influence_rel.properties.get("explanation") == "Team lead"
