"""Stub NLP extraction module for LOGOS."""

from __future__ import annotations

import re
from typing import Any, Dict, List


_PERSON_PATTERN = re.compile(r"\b([A-Z][a-z]+ [A-Z][a-z]+)\b")
_ORG_PATTERN = re.compile(
    r"\b([A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*)*\s+(?:Pty Ltd|Pty|Ltd|LLC|Inc|Corporation|Corp|Company))\b"
)
_COMMITMENT_PATTERN = re.compile(r"\b(?:will|shall)\b[^.]*?\bby\s+[^\.\n]+", re.IGNORECASE)


def _extract_entities(text: str) -> Dict[str, List[str]]:
    persons = _PERSON_PATTERN.findall(text)
    orgs = _ORG_PATTERN.findall(text)
    commitments = _COMMITMENT_PATTERN.findall(text)
    return {
        "persons": persons,
        "orgs": orgs,
        "projects": [],
        "contracts": [],
        "topics": [],
        "commitments": commitments,
    }


def extract_all(text: str) -> Dict[str, Any]:
    """Extract entities, relationships, and sentiment from raw text."""
    entities = _extract_entities(text)
    summary = text[:140]
    # Basic neutral sentiment placeholder; real implementation would use model outputs.
    sentiment = 0.0
    return {
        "entities": entities,
        "relationships": [],
        "sentiment": sentiment,
        "summary": summary,
    }
