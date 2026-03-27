from __future__ import annotations

import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from logos.contradictions.models import BeliefPointer, ContradictionRecord
from logos.contradictions.projection import ContradictionProjection


class FakeNeo4jClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def run(self, query: str, params=None):  # type: ignore[override]
        self.calls.append((query, params or {}))
        if "RETURN b.id AS id" in query:
            return [
                {
                    "id": "b_existing",
                    "subject_ref": "Person:p1",
                    "predicate": "OWNS",
                    "object_ref": "Asset:a1",
                    "statement": "{}",
                    "metadata": "{}",
                }
            ]
        return []


def test_projection_persists_contradiction_and_tension_relationships() -> None:
    client = FakeNeo4jClient()
    projection = ContradictionProjection(client)

    contradiction = ContradictionRecord(
        id="ctr_1",
        type="hard",
        code="cardinality_conflict",
        explanation="cardinality clash",
        recommended_resolution="resolve",
        involved_beliefs=[
            BeliefPointer(belief_id="b_new", subject_ref="Person:p1", predicate="OWNS", object_ref="Asset:a2"),
            BeliefPointer(belief_id="b_existing", subject_ref="Person:p1", predicate="OWNS", object_ref="Asset:a1"),
        ],
    )

    summary = projection.persist([contradiction])

    assert summary["contradictions"] == 1
    assert summary["involves"] == 2
    assert summary["dialectical_tensions"] == 1
    assert any("MERGE (c:Contradiction" in query for query, _ in client.calls)
    assert any("MERGE (c)-[r:INVOLVES]->(b)" in query for query, _ in client.calls)
    assert any("DIALECTICAL_TENSION" in query for query, _ in client.calls)


def test_fetch_existing_beliefs_by_subject_predicate() -> None:
    client = FakeNeo4jClient()
    projection = ContradictionProjection(client)

    rows = projection.fetch_existing_beliefs_for_subject_predicates([("Person:p1", "OWNS")], exclude_belief_ids=["b_new"])

    assert len(rows) == 1
    assert rows[0]["id"] == "b_existing"
