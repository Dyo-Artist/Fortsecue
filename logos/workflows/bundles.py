"""Compatibility re-exports for pipeline bundles.

The canonical bundle contracts live in :mod:`logos.models.bundles`. This module
keeps the workflow imports stable while the pipelines migrate to the typed
models.
"""
from logos.models.bundles import (  # noqa: F401
    EntityMention,
    ExtractionBundle,
    InteractionMeta,
    ParsedContentBundle,
    PipelineBundle,
    PreviewBundle,
    RawInputBundle,
)

__all__ = [
    "PipelineBundle",
    "RawInputBundle",
    "ParsedContentBundle",
    "ExtractionBundle",
    "InteractionMeta",
    "PreviewBundle",
    "EntityMention",
]
