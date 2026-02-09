from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

LABEL_PATTERN = re.compile(r"^[A-Z][A-Za-z0-9_]*$")
REL_TYPE_PATTERN = re.compile(r"^[A-Z0-9_]+$")


def _ensure_valid_label(label: str) -> str:
    candidate = label[0].upper() + label[1:] if label else label
    if not LABEL_PATTERN.match(candidate):
        raise ValueError(f"Invalid node label: {label}")
    return candidate


def _ensure_valid_rel_type(rel_type: str) -> str:
    if not REL_TYPE_PATTERN.match(rel_type):
        raise ValueError(f"Invalid relationship type: {rel_type}")
    return rel_type


class GraphNode(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    label: str
    properties: dict[str, Any] = Field(default_factory=dict)
    concept_id: str | None = None
    concept_kind: str | None = None
    source_uri: str | None = None

    @field_validator("label")
    @classmethod
    def _validate_label(cls, value: str) -> str:
        return _ensure_valid_label(value)


class GraphRelationship(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    src: str
    dst: str
    rel_type: str = Field(alias="rel")
    src_label: str | None = None
    dst_label: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    source_uri: str | None = None

    @field_validator("rel_type")
    @classmethod
    def _validate_rel(cls, value: str) -> str:
        return _ensure_valid_rel_type(value.upper())

    @field_validator("src_label", "dst_label")
    @classmethod
    def _validate_optional_labels(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _ensure_valid_label(value)

    @property
    def rel(self) -> str:
        """Backwards-compatible access to the relationship type."""

        return self.rel_type


__all__ = [
    "GraphNode",
    "GraphRelationship",
    "LABEL_PATTERN",
    "REL_TYPE_PATTERN",
    "_ensure_valid_label",
    "_ensure_valid_rel_type",
]
