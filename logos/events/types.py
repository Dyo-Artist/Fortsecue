"""Typed event envelope models for LOGOS event streaming."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class EventEnvelope(BaseModel):
    """Standard event envelope shared by event bus backends and APIs."""

    model_config = ConfigDict(extra="allow")

    event_id: str = Field(default_factory=lambda: uuid4().hex)
    event_type: str = Field(min_length=1)
    schema_version: str = Field(default="1.0")
    occurred_at: datetime = Field(default_factory=_utc_now)
    producer: str = Field(min_length=1)
    correlation_id: str | None = None
    causation_id: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    provenance: dict[str, object] = Field(default_factory=dict)
    payload: dict[str, object] = Field(default_factory=dict)

    @field_validator("occurred_at")
    @classmethod
    def _normalise_occurred_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
