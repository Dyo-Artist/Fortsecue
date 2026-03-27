from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol

logger = logging.getLogger(__name__)


class BeliefStore(Protocol):
    """Persistence interface for belief read-model projection."""

    def ensure_indexes(self) -> None:
        """Create required graph constraints/indexes if missing."""

    def upsert_belief(self, belief: Mapping[str, Any], now: datetime | None = None) -> None:
        """Idempotently upsert a Belief node."""

    def attach_support(self, *, belief_id: str, evidence: Mapping[str, Any], now: datetime | None = None) -> None:
        """Create SUPPORTS relationship from Evidence/Event to Belief."""

    def attach_about(self, *, belief_id: str, entity_id: str) -> None:
        """Create ABOUT relationship from Belief to entity node."""


class Neo4jBeliefStore:
    """Neo4j-backed BeliefStore implementation using parameterized MERGE statements."""

    def __init__(self, client: Any, *, ensure_constraints: bool = True) -> None:
        self._client = client
        self._constraints_ready = False
        if ensure_constraints:
            self.ensure_indexes()

    @staticmethod
    def _utcnow(now: datetime | None = None) -> datetime:
        return now if isinstance(now, datetime) else datetime.now(timezone.utc)

    def ensure_indexes(self) -> None:
        if self._constraints_ready:
            return
        self._client.run(
            "CREATE CONSTRAINT IF NOT EXISTS FOR (b:Belief) REQUIRE b.id IS UNIQUE",
            {},
        )
        self._constraints_ready = True

    def upsert_belief(self, belief: Mapping[str, Any], now: datetime | None = None) -> None:
        timestamp = self._utcnow(now)
        statement = belief.get("statement") if isinstance(belief.get("statement"), Mapping) else {}
        provenance = belief.get("provenance") if isinstance(belief.get("provenance"), Mapping) else {}
        predicate = statement.get("predicate") if isinstance(statement.get("predicate"), str) else belief.get("predicate")

        subject = statement.get("subject") if isinstance(statement.get("subject"), Mapping) else {}
        obj = statement.get("object") if isinstance(statement.get("object"), Mapping) else {}

        params = {
            "belief_id": str(belief.get("id", "")),
            "status": str(belief.get("status", "candidate")),
            "polarity": str(belief.get("polarity", "unknown")),
            "predicate": str(predicate or ""),
            "subject_ref": str(subject.get("ref") or ""),
            "object_ref": str(obj.get("ref") or obj.get("value") or ""),
            "confidence": float(belief.get("confidence", 0.5) or 0.5),
            "created_at": timestamp,
            "updated_at": timestamp,
            "statement_json": json.dumps(statement, sort_keys=True, ensure_ascii=False),
            "provenance_json": json.dumps(provenance, sort_keys=True, ensure_ascii=False),
        }

        self._client.run(
            """
            MERGE (b:Belief {id: $belief_id})
            ON CREATE SET
                b.created_at = $created_at
            SET
                b.status = $status,
                b.polarity = $polarity,
                b.predicate = $predicate,
                b.confidence = $confidence,
                b.subject_ref = $subject_ref,
                b.object_ref = $object_ref,
                b.statement = $statement_json,
                b.provenance = $provenance_json,
                b.updated_at = $updated_at
            """,
            params,
        )

    def attach_support(self, *, belief_id: str, evidence: Mapping[str, Any], now: datetime | None = None) -> None:
        timestamp = self._utcnow(now)
        event_id = evidence.get("event_id")
        source_uri = evidence.get("source_uri")
        confidence = float(evidence.get("confidence", 0.5) or 0.5)

        if event_id:
            self._client.run(
                """
                MATCH (b:Belief {id: $belief_id})
                MERGE (e:Event {id: $event_id})
                ON CREATE SET e.created_at = $created_at
                SET e.updated_at = $updated_at
                MERGE (e)-[r:SUPPORTS]->(b)
                SET r.confidence = $confidence,
                    r.updated_at = $updated_at,
                    r.source_uri = coalesce($source_uri, r.source_uri)
                """,
                {
                    "belief_id": belief_id,
                    "event_id": str(event_id),
                    "source_uri": str(source_uri) if source_uri is not None else None,
                    "confidence": confidence,
                    "created_at": timestamp,
                    "updated_at": timestamp,
                },
            )
            return

        evidence_id = evidence.get("id") or f"evidence_{belief_id}"
        self._client.run(
            """
            MATCH (b:Belief {id: $belief_id})
            MERGE (e:Evidence {id: $evidence_id})
            ON CREATE SET e.created_at = $created_at
            SET
                e.updated_at = $updated_at,
                e.source_uri = coalesce($source_uri, e.source_uri)
            MERGE (e)-[r:SUPPORTS]->(b)
            SET
                r.confidence = $confidence,
                r.updated_at = $updated_at,
                r.source_uri = coalesce($source_uri, r.source_uri)
            """,
            {
                "belief_id": belief_id,
                "evidence_id": str(evidence_id),
                "source_uri": str(source_uri) if source_uri is not None else None,
                "confidence": confidence,
                "created_at": timestamp,
                "updated_at": timestamp,
            },
        )

    def attach_about(self, *, belief_id: str, entity_id: str) -> None:
        if not entity_id:
            return
        self._client.run(
            """
            MATCH (b:Belief {id: $belief_id})
            MATCH (n {id: $entity_id})
            WHERE NOT n:Belief
            MERGE (b)-[:ABOUT]->(n)
            """,
            {"belief_id": belief_id, "entity_id": entity_id},
        )
        logger.debug("belief_about_attached", extra={"belief_id": belief_id, "entity_id": entity_id})
