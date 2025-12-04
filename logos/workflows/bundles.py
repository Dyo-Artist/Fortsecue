from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class PipelineBundle(BaseModel):
    """Base class for pipeline bundles passed between stages."""

    model_config = ConfigDict(extra="allow")


class RawInputBundle(PipelineBundle):
    """Raw input payload captured at ingest."""

    text: str
    source_uri: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ParsedContentBundle(PipelineBundle):
    """Parsed content representation with tokenised text."""

    text: str
    tokens: List[str] = Field(default_factory=list)
    source_uri: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ExtractionBundle(PipelineBundle):
    """Lightweight extraction result used by stub pipelines."""

    text: str
    tokens: List[str] = Field(default_factory=list)
    summary: str = ""
    source_uri: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

