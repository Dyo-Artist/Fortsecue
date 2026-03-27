"""Models and interfaces for LOGOS meta-controller orchestration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from logos.events.types import EventEnvelope


class ModuleContext(BaseModel):
    """Execution context shared with meta modules."""

    model_config = ConfigDict(extra="allow")

    activation: float = Field(default=0.0, ge=0.0)
    mode: str = Field(default="shadow")
    event_loop_mode: str = Field(default="unified")
    metadata: dict[str, Any] = Field(default_factory=dict)


class Suggestion(BaseModel):
    """Suggestion output from a module; becomes logos.suggestion.* event(s)."""

    model_config = ConfigDict(extra="allow")

    suggestion_type: str = Field(min_length=1)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    payload: dict[str, Any] = Field(default_factory=dict)


class ModuleOutput(BaseModel):
    """Structured outputs from a single module invocation."""

    events_out: list[EventEnvelope] = Field(default_factory=list)
    suggestions_out: list[Suggestion] = Field(default_factory=list)


class ModuleProtocol(Protocol):
    """Meta module contract: (event, context) -> (events_out, suggestions_out)."""

    name: str

    def __call__(
        self,
        event: EventEnvelope,
        context: ModuleContext,
    ) -> tuple[list[EventEnvelope], list[Suggestion]]:
        ...


def metadata_with_default(
    metadata: Mapping[str, Any] | None,
    *,
    defaults: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = dict(defaults or {})
    if metadata:
        payload.update(dict(metadata))
    return payload
