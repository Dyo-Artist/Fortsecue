from __future__ import annotations

import logging
from typing import Any, Mapping

from logos.beliefs.store import BeliefStore

logger = logging.getLogger(__name__)


class BeliefProjection:
    """Project belief candidates into Neo4j as a non-destructive read-model."""

    def __init__(self, store: BeliefStore) -> None:
        self._store = store
        self._store.ensure_indexes()

    @staticmethod
    def _entity_ids_from_belief(belief: Mapping[str, Any]) -> set[str]:
        statement = belief.get("statement") if isinstance(belief.get("statement"), Mapping) else {}
        refs: set[str] = set()

        for term_key in ("subject", "object"):
            term = statement.get(term_key) if isinstance(statement.get(term_key), Mapping) else {}
            ref = term.get("ref")
            if not isinstance(ref, str) or not ref:
                continue
            if ":" in ref:
                refs.add(ref.split(":", maxsplit=1)[1])
            else:
                refs.add(ref)
        return refs

    def apply(self, candidates: Mapping[str, Any] | None) -> dict[str, int]:
        if not isinstance(candidates, Mapping):
            return {"beliefs": 0, "supports": 0, "about": 0}

        beliefs = candidates.get("beliefs") if isinstance(candidates.get("beliefs"), list) else []
        evidence_items = candidates.get("evidence") if isinstance(candidates.get("evidence"), list) else []

        evidence_by_belief: dict[str, list[Mapping[str, Any]]] = {}
        for item in evidence_items:
            if not isinstance(item, Mapping):
                continue
            belief_id = item.get("belief_id")
            if isinstance(belief_id, str) and belief_id:
                evidence_by_belief.setdefault(belief_id, []).append(item)

        supports = 0
        about = 0
        projected = 0

        for belief in beliefs:
            if not isinstance(belief, Mapping):
                continue
            belief_id = belief.get("id")
            if not isinstance(belief_id, str) or not belief_id:
                continue

            self._store.upsert_belief(belief)
            projected += 1

            for evidence in evidence_by_belief.get(belief_id, []):
                self._store.attach_support(belief_id=belief_id, evidence=evidence)
                supports += 1

            for entity_id in self._entity_ids_from_belief(belief):
                self._store.attach_about(belief_id=belief_id, entity_id=entity_id)
                about += 1

        logger.info("belief_projection_applied", extra={"beliefs": projected, "supports": supports, "about": about})
        return {"beliefs": projected, "supports": supports, "about": about}
