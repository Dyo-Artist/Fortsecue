from __future__ import annotations

import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from logos.beliefs import BeliefProjection, Neo4jBeliefStore


class FakeNeo4jClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def run(self, query: str, params=None):  # type: ignore[override]
        self.calls.append((query, params or {}))
        return []


def _candidate_payload() -> dict:
    return {
        "beliefs": [
            {
                "id": "belief_123",
                "status": "candidate",
                "polarity": "unknown",
                "confidence": 0.81,
                "statement": {
                    "subject": {"ref": "Person:p1"},
                    "predicate": "WORKS_WITH",
                    "object": {"ref": "Org:o1"},
                },
                "provenance": {
                    "source_uri": "file:///tmp/meeting.txt",
                    "supporting_event_ids": ["evt-77"],
                },
            }
        ],
        "evidence": [
            {
                "id": "evidence_belief_123",
                "belief_id": "belief_123",
                "event_id": "evt-77",
                "source_uri": "file:///tmp/meeting.txt",
                "confidence": 0.81,
            }
        ],
    }


def test_belief_store_initialization_creates_constraint_once() -> None:
    client = FakeNeo4jClient()
    store = Neo4jBeliefStore(client)

    store.ensure_indexes()

    constraint_calls = [call for call, _ in client.calls if "CREATE CONSTRAINT IF NOT EXISTS FOR (b:Belief)" in call]
    assert len(constraint_calls) == 1


def test_projection_merges_belief_by_id_and_creates_about_relationships() -> None:
    client = FakeNeo4jClient()
    projection = BeliefProjection(Neo4jBeliefStore(client))

    summary = projection.apply(_candidate_payload())

    assert summary["beliefs"] == 1
    assert summary["supports"] == 1
    assert summary["about"] == 2

    merge_calls = [(q, p) for q, p in client.calls if "MERGE (b:Belief {id: $belief_id})" in q]
    assert merge_calls, "Belief MERGE query should be executed"
    assert merge_calls[0][1]["belief_id"] == "belief_123"

    about_calls = [q for q, _ in client.calls if "MERGE (b)-[:ABOUT]->(n)" in q]
    assert len(about_calls) == 2
