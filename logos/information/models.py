from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class InformationBaseModel(BaseModel):
    """Base model for information-native artifacts.

    The information substrate is schema-flexible by design, so models permit
    extra fields to preserve forward-compatibility as the knowledgebase evolves.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True, str_strip_whitespace=True)


class Provenance(InformationBaseModel):
    """Source and traceability metadata shared by InformationObjects and Beliefs."""

    source_uri: str | None = None
    source_type: str | None = None
    supporting_event_ids: list[str] = Field(default_factory=list)
    pipeline_id: str | None = None
    extracted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)


class BeliefStatus(str, Enum):
    CANDIDATE = "candidate"
    SUPPORTED = "supported"
    CONTESTED = "contested"
    REJECTED = "rejected"


class Polarity(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    UNKNOWN = "unknown"


class BeliefTerm(InformationBaseModel):
    """Term in a belief statement."""

    ref: str
    label: str | None = None
    value: Any | None = None


class BeliefStatement(InformationBaseModel):
    """Structured subject-predicate-object statement."""

    subject: BeliefTerm
    predicate: str
    object: BeliefTerm


class InformationObject(InformationBaseModel):
    """Canonical container for meaningful payloads in LOGOS."""

    id: str | None = None
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance = Field(default_factory=Provenance)
    embeddings: list[float] | None = None
    confidence: float | None = None

    @field_validator("confidence")
    @classmethod
    def _validate_optional_confidence(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if value < 0.0 or value > 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        return float(value)


class Belief(InformationBaseModel):
    """Hypothesis-level assertion with confidence and provenance."""

    id: str
    statement: BeliefStatement
    polarity: Polarity = Polarity.UNKNOWN
    confidence: float = 0.5
    provenance: Provenance = Field(default_factory=Provenance)
    status: BeliefStatus = BeliefStatus.CANDIDATE
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("confidence")
    @classmethod
    def _validate_confidence(cls, value: float) -> float:
        if value < 0.0 or value > 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        return float(value)


class Evidence(InformationBaseModel):
    """Evidence linking beliefs to concrete events/sources."""

    id: str
    belief_id: str
    relation_type: str = "supports"
    event_id: str | None = None
    source_uri: str | None = None
    confidence: float = 0.5
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("confidence")
    @classmethod
    def _validate_confidence(cls, value: float) -> float:
        if value < 0.0 or value > 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        return float(value)


class BeliefConversionResult(InformationBaseModel):
    """Return type for conversion utilities."""

    beliefs: list[Belief] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    contradiction_markers: list[dict[str, Any]] = Field(default_factory=list)
