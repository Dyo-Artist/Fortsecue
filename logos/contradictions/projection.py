from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Mapping

from .models import ContradictionRecord


class ContradictionProjection:
    """Persist contradiction artifacts and tension links into Neo4j."""

    def __init__(self, client: Any, *, create_tension_edges: bool = True) -> None:
        self._client = client
        self._create_tension_edges = create_tension_edges
        self._constraints_ready = False

    def ensure_indexes(self) -> None:
        if self._constraints_ready:
            return
        self._client.run(
            "CREATE CONSTRAINT IF NOT EXISTS FOR (c:Contradiction) REQUIRE c.id IS UNIQUE",
            {},
        )
        self._constraints_ready = True

    def fetch_existing_beliefs_for_subject_predicates(
        self,
        pairs: list[tuple[str, str]],
        *,
        exclude_belief_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        if not pairs:
            return []

        result = self._client.run(
            """
            UNWIND $pairs AS pair
            MATCH (b:Belief)
            WHERE b.subject_ref = pair.subject_ref
              AND b.predicate = pair.predicate
              AND NOT b.id IN $exclude_ids
            RETURN b.id AS id,
                   b.subject_ref AS subject_ref,
                   b.predicate AS predicate,
                   b.object_ref AS object_ref,
                   b.statement AS statement,
                   b.metadata AS metadata
            """,
            {"pairs": [{"subject_ref": s, "predicate": p} for s, p in pairs], "exclude_ids": exclude_belief_ids or []},
        )
        return [dict(row) for row in result]

    def persist(self, contradictions: list[ContradictionRecord], *, now: datetime | None = None) -> dict[str, int]:
        if not contradictions:
            return {"contradictions": 0, "involves": 0, "dialectical_tensions": 0}

        self.ensure_indexes()
        timestamp = now or datetime.now(timezone.utc)

        contradiction_count = 0
        involves_count = 0
        tension_count = 0

        for contradiction in contradictions:
            payload = contradiction.model_dump()
            payload["created_at"] = timestamp
            payload["updated_at"] = timestamp
            payload["metadata_json"] = json.dumps(contradiction.metadata, sort_keys=True, ensure_ascii=False)

            self._client.run(
                """
                MERGE (c:Contradiction {id: $id})
                ON CREATE SET c.created_at = $created_at
                SET c.type = $type,
                    c.code = $code,
                    c.explanation = $explanation,
                    c.recommended_resolution = $recommended_resolution,
                    c.confidence = $confidence,
                    c.metadata = $metadata_json,
                    c.updated_at = $updated_at
                """,
                payload,
            )
            contradiction_count += 1

            belief_ids: list[str] = []
            for pointer in contradiction.involved_beliefs:
                belief_id = pointer.belief_id
                if not belief_id:
                    continue
                belief_ids.append(belief_id)
                self._client.run(
                    """
                    MATCH (c:Contradiction {id: $contradiction_id})
                    MATCH (b:Belief {id: $belief_id})
                    MERGE (c)-[r:INVOLVES]->(b)
                    SET r.updated_at = $updated_at
                    """,
                    {
                        "contradiction_id": contradiction.id,
                        "belief_id": belief_id,
                        "updated_at": timestamp,
                    },
                )
                involves_count += 1

            if self._create_tension_edges and len(belief_ids) >= 2:
                self._client.run(
                    """
                    MATCH (a:Belief {id: $left_id})
                    MATCH (b:Belief {id: $right_id})
                    MERGE (a)-[r:DIALECTICAL_TENSION {contradiction_id: $contradiction_id}]->(b)
                    SET r.code = $code,
                        r.type = $type,
                        r.updated_at = $updated_at
                    """,
                    {
                        "left_id": belief_ids[0],
                        "right_id": belief_ids[1],
                        "contradiction_id": contradiction.id,
                        "code": contradiction.code,
                        "type": contradiction.type,
                        "updated_at": timestamp,
                    },
                )
                tension_count += 1

        return {
            "contradictions": contradiction_count,
            "involves": involves_count,
            "dialectical_tensions": tension_count,
        }


def belief_subject_predicate_pairs(beliefs: list[Mapping[str, Any]]) -> list[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for belief in beliefs:
        statement = belief.get("statement") if isinstance(belief.get("statement"), Mapping) else {}
        subject = statement.get("subject") if isinstance(statement.get("subject"), Mapping) else {}
        subject_ref = belief.get("subject_ref") or subject.get("ref")
        predicate = belief.get("predicate") or statement.get("predicate")
        if isinstance(subject_ref, str) and subject_ref and isinstance(predicate, str) and predicate:
            pairs.add((subject_ref, predicate))
    return sorted(pairs)
