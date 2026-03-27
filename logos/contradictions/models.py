from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Mapping
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class ContradictionBaseModel(BaseModel):
    """Base contradiction model with flexible extras for evolving schema support."""

    model_config = ConfigDict(extra="allow", populate_by_name=True, str_strip_whitespace=True)


class BeliefPointer(ContradictionBaseModel):
    """Reference to a belief participating in a contradiction artifact."""

    belief_id: str
    subject_ref: str | None = None
    predicate: str | None = None
    object_ref: str | None = None


class ContradictionRecord(ContradictionBaseModel):
    """First-class contradiction artifact persisted to the graph."""

    id: str = Field(default_factory=lambda: f"ctr_{uuid4().hex}")
    type: Literal["hard", "soft", "paradoxical"]
    code: str
    explanation: str
    recommended_resolution: str
    involved_beliefs: list[BeliefPointer] = Field(default_factory=list)
    confidence: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ContradictionDetectionResult(ContradictionBaseModel):
    """Container for contradiction records and summary counts."""

    contradictions: list[ContradictionRecord] = Field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        totals = {"hard": 0, "soft": 0, "paradoxical": 0}
        for item in self.contradictions:
            totals[item.type] = totals.get(item.type, 0) + 1
        totals["total"] = len(self.contradictions)
        return totals


class PredicateConstraint(ContradictionBaseModel):
    """Runtime KB constraint model for contradiction policy."""

    predicate: str
    cardinality: int | None = None
    conflict_code: str = "value_disagreement"
    recommended_resolution: str = "Inspect supporting evidence and adjudicate manually."


class TemporalRule(ContradictionBaseModel):
    """Rule defining temporal contradiction behavior for a predicate."""

    predicate: str
    overlap_conflict: bool = True
    start_key: str = "start_at"
    end_key: str = "end_at"
    conflict_code: str = "temporal_overlap"
    recommended_resolution: str = "Add explicit effective windows or supersession metadata."


class ContradictionRules(ContradictionBaseModel):
    """Knowledgebase-backed contradiction policy."""

    hard_constraints: list[PredicateConstraint] = Field(default_factory=list)
    soft_constraints: list[PredicateConstraint] = Field(default_factory=list)
    temporal_rules: list[TemporalRule] = Field(default_factory=list)
    paradox_allowlist: list[Mapping[str, Any]] = Field(default_factory=list)
