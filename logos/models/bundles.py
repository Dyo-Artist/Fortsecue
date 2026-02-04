"""Typed bundle contracts for LOGOS pipelines.

These bundles formalise the shapes passed between ingest → parse → extract →
normalise → graph upsert. The schema is intentionally flexible to allow the
knowledgebase to evolve without code changes while still providing predictable
contract fields for each stage.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Literal, Mapping, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LogosBaseModel(BaseModel):
    """Base model with permissive extras for evolving schema support."""

    model_config = ConfigDict(extra="allow", populate_by_name=True, str_strip_whitespace=True)


class PipelineBundle(LogosBaseModel):
    """Base class for all pipeline bundles."""

    bundle_version: str = "0.1"
    processing_version: str = "0.1"


class InteractionMeta(LogosBaseModel):
    """Metadata describing a single interaction in the pipeline."""

    interaction_id: str
    interaction_type: str
    interaction_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_uri: Optional[str] = None
    source_type: Literal["doc", "audio", "text"] = "text"
    created_by: Optional[str] = None
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    project_id: Optional[str] = None
    contract_id: Optional[str] = None


class EntityMention(LogosBaseModel):
    """Entity mention extracted from content."""

    id: Optional[str] = None
    temp_id: Optional[str] = None
    canonical_id: Optional[str] = None
    label: Optional[str] = None
    name: Optional[str] = None
    confidence: Optional[float] = None
    action: Optional[Literal["create", "keep", "link", "ignore"]] = None


class Relationship(LogosBaseModel):
    """Relationship candidate between entities."""

    src: str
    dst: str
    rel: str
    confidence: Optional[float] = None
    action: Optional[Literal["create", "keep", "link", "ignore"]] = None
    properties: Dict[str, Any] = Field(default_factory=dict)


class InteractionSnapshot(LogosBaseModel):
    """Preview interaction summary used for UI rendering."""

    summary: Optional[str] = None
    subject: Optional[str] = None
    at: Optional[datetime | str] = None
    sentiment: Optional[float | str] = None


class RawInputBundle(PipelineBundle):
    """Raw input payload captured at ingest."""

    meta: InteractionMeta
    raw_file_path: Optional[str] = None
    raw_text: Optional[str] = Field(default=None, alias="text")
    content_hash: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @property
    def text(self) -> str:
        return self.raw_text or ""

    @model_validator(mode="before")
    @classmethod
    def _ensure_meta(cls, value: Any) -> Any:
        if isinstance(value, Mapping) and not value.get("meta"):
            metadata = value.get("metadata") if isinstance(value.get("metadata"), Mapping) else {}
            interaction_type = metadata.get("type") if isinstance(metadata, Mapping) else None
            value = dict(value)
            value["meta"] = InteractionMeta(
                interaction_id=str(value.get("interaction_id") or uuid4().hex),
                interaction_type=str(interaction_type or value.get("interaction_type") or "interaction"),
                interaction_at=value.get("interaction_at") or datetime.now(timezone.utc),
                source_uri=value.get("source_uri") or value.get("raw_file_path"),
                source_type=str(value.get("source_type") or "text"),
                created_by=str(value.get("created_by")) if value.get("created_by") is not None else None,
                received_at=value.get("received_at") or datetime.now(timezone.utc),
                project_id=value.get("project_id"),
                contract_id=value.get("contract_id"),
            )
        return value


class ParsedContentBundle(PipelineBundle):
    """Parsed content with optional structural hints."""

    meta: InteractionMeta
    text: str = Field(default="", alias="raw_text")
    structure: Optional[Mapping[str, Any]] = None
    language: Optional[str] = None
    doc_date: Optional[date] = None
    tokens: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ExtractionBundle(PipelineBundle):
    """Extraction results including entities, relationships, and metrics."""

    meta: InteractionMeta
    text: str
    tokens: List[str] = Field(default_factory=list)
    summary: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)
    extraction: Dict[str, Any] = Field(default_factory=dict)
    entities: Dict[str, List[EntityMention]] = Field(default_factory=dict)
    relationships: List[Relationship] = Field(default_factory=list)
    metrics: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _ensure_meta(cls, value: Any) -> Any:
        if isinstance(value, Mapping) and not value.get("meta"):
            metadata = value.get("metadata") if isinstance(value.get("metadata"), Mapping) else {}
            interaction_type = metadata.get("type") if isinstance(metadata, Mapping) else None
            value = dict(value)
            value["meta"] = InteractionMeta(
                interaction_id=str(value.get("interaction_id") or uuid4().hex),
                interaction_type=str(interaction_type or value.get("interaction_type") or "interaction"),
                interaction_at=value.get("interaction_at") or datetime.now(timezone.utc),
                source_uri=value.get("source_uri"),
                source_type=str(value.get("source_type") or "text"),
                created_by=str(value.get("created_by")) if value.get("created_by") is not None else None,
                received_at=value.get("received_at") or datetime.now(timezone.utc),
                project_id=value.get("project_id"),
                contract_id=value.get("contract_id"),
            )
        return value

    @classmethod
    def from_raw(
        cls,
        raw_text: str,
        meta: InteractionMeta,
        *,
        tokens: Optional[List[str]] = None,
        summary: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        entities: Optional[Dict[str, List[Mapping[str, Any]]]] = None,
        relationships: Optional[List[Mapping[str, Any]]] = None,
        metrics: Optional[Dict[str, Any]] = None,
        extraction: Optional[Dict[str, Any]] = None,
    ) -> "ExtractionBundle":
        return cls(
            meta=meta,
            text=raw_text,
            tokens=tokens or [],
            summary=summary or "",
            metadata=metadata or {},
            extraction=extraction or {},
            entities={k: [EntityMention.model_validate(e) for e in v] for k, v in (entities or {}).items()},
            relationships=[Relationship.model_validate(rel) for rel in relationships or []],
            metrics=metrics or {},
        )


class ResolvedBundle(PipelineBundle):
    """Entity/relationship resolution output.

    Resolution emits canonical ids, candidate matches, and confidence signals.
    Preview workflows typically map this state into PreviewBundle for UI edits.
    """

    meta: InteractionMeta
    resolved_entities: Dict[str, List[EntityMention]] = Field(default_factory=dict)
    resolved_relationships: List[Relationship] = Field(default_factory=list)
    low_confidence_flags: List[str] = Field(default_factory=list)


class PreviewEntity(EntityMention):
    """Entity representation for previews."""

    is_new: Optional[bool] = None


class PreviewBundle(PipelineBundle):
    """Preview payload returned to clients.

    This bundle carries the resolved, editable snapshot presented to users
    before commit, so it effectively serves as the resolved bundle in review.
    """

    meta: InteractionMeta
    interaction: InteractionSnapshot
    entities: Dict[str, List[PreviewEntity]] = Field(default_factory=dict)
    relationships: List[Relationship] = Field(default_factory=list)
    ready: bool = True

    @model_validator(mode="before")
    @classmethod
    def _ensure_ready(cls, value: Any) -> Any:
        if isinstance(value, Mapping) and "ready" not in value:
            value = dict(value)
            value["ready"] = True
        return value


class UpsertBundle(PipelineBundle):
    """Graph-ready payloads for commit.

    Upsert bundles must be fully materialised: all nodes have stable ids and
    relationships reference those ids directly for idempotent MERGE upserts.
    """

    meta: InteractionMeta
    nodes: List[Mapping[str, Any]] = Field(default_factory=list)
    relationships: List[Mapping[str, Any]] = Field(default_factory=list)
    # TODO: expand when commit pipeline is formalised


class ReasoningBundle(PipelineBundle):
    """Placeholder for reasoning traces and observations."""

    meta: InteractionMeta
    traces: List[Any] = Field(default_factory=list)
    notes: Optional[str] = None
    # TODO: include evaluation metrics, prompts, and revision history


class FeedbackBundle(PipelineBundle):
    """Placeholder for user feedback on pipeline outputs."""

    meta: InteractionMeta
    feedback: Optional[str] = None
    rating: Optional[int] = None
    # TODO: capture structured feedback for learning loops


__all__ = [
    "EntityMention",
    "FeedbackBundle",
    "InteractionMeta",
    "InteractionSnapshot",
    "ParsedContentBundle",
    "PipelineBundle",
    "PreviewBundle",
    "PreviewEntity",
    "RawInputBundle",
    "ReasoningBundle",
    "Relationship",
    "ResolvedBundle",
    "UpsertBundle",
    "ExtractionBundle",
]
