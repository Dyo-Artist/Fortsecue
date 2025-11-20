"""Ingest layer helpers for LOGOS."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Tuple


def doc_ingest(payload: dict[str, Any]) -> Tuple[dict[str, Any], str]:
    """Prepare a document interaction stub and return the raw text."""
    text = payload.get("text", "")
    source_uri = payload.get("source_uri", "")
    interaction = {
        "type": "document",
        "at": datetime.now(timezone.utc),
        "source_uri": source_uri,
    }
    return interaction, text


def note_ingest(payload: dict[str, Any]) -> Tuple[dict[str, Any], str]:
    """Prepare a note interaction stub and return the raw text."""
    text = payload.get("text", "")
    interaction = {
        "type": "note",
        "at": datetime.now(timezone.utc),
        "source_uri": payload.get("source_uri", ""),
    }
    if payload.get("topic"):
        interaction["topic"] = payload["topic"]
    return interaction, text
