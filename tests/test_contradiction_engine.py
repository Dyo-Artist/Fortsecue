from __future__ import annotations

import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from logos.contradictions.engine import ContradictionEngine


def _belief(belief_id: str, subject_ref: str, predicate: str, object_ref: str) -> dict:
    return {
        "id": belief_id,
        "statement": {
            "subject": {"ref": subject_ref, "label": "Entity"},
            "predicate": predicate,
            "object": {"ref": object_ref, "label": "Entity"},
        },
    }


def test_hard_contradiction_cardinality_one() -> None:
    engine = ContradictionEngine(
        {
            "hard_constraints": [
                {
                    "predicate": "OWNS",
                    "cardinality": 1,
                    "conflict_code": "cardinality_conflict",
                }
            ]
        }
    )

    result = engine.detect(
        new_beliefs=[_belief("b_new", "Person:p1", "OWNS", "Asset:a2")],
        existing_beliefs=[_belief("b_old", "Person:p1", "OWNS", "Asset:a1")],
    )

    assert result.counts["hard"] == 1
    assert result.contradictions[0].code == "cardinality_conflict"


def test_soft_contradiction_multi_value_allowed() -> None:
    engine = ContradictionEngine(
        {
            "soft_constraints": [
                {
                    "predicate": "WORKS_WITH",
                    "conflict_code": "value_disagreement",
                }
            ]
        }
    )

    result = engine.detect(
        new_beliefs=[_belief("b_new", "Person:p1", "WORKS_WITH", "Org:o2")],
        existing_beliefs=[_belief("b_old", "Person:p1", "WORKS_WITH", "Org:o1")],
    )

    assert result.counts["soft"] == 1
    assert result.contradictions[0].type == "soft"


def test_paradox_allowlist_promotes_paradoxical_classification() -> None:
    engine = ContradictionEngine(
        {
            "hard_constraints": [
                {
                    "predicate": "STATE",
                    "cardinality": 1,
                    "conflict_code": "identity_conflict",
                }
            ],
            "paradox_allowlist": [
                {
                    "predicate": "STATE",
                    "subject_ref": "Concept:schrodinger_cat",
                }
            ],
        }
    )

    result = engine.detect(
        new_beliefs=[_belief("b_new", "Concept:schrodinger_cat", "STATE", "State:alive")],
        existing_beliefs=[_belief("b_old", "Concept:schrodinger_cat", "STATE", "State:dead")],
    )

    assert result.counts["paradoxical"] == 1
    assert result.contradictions[0].type == "paradoxical"
