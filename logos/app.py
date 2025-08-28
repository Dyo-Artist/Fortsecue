"""LOGOS FastAPI application.

This module defines a single endpoint used to ingest documents and
produce a preview of detected entities and relationships. A very naive
heuristic is used to pull out people, organisations and commitments from
the submitted text. Each preview is stored in-memory keyed by a generated
interaction id.
"""

from __future__ import annotations

import re
from datetime import datetime
from uuid import uuid4

from fastapi import FastAPI
from pydantic import BaseModel


app = FastAPI()


class Doc(BaseModel):
    """Input payload for document ingestion."""

    source_uri: str
    text: str


# simple in-memory store of previews keyed by interaction id
PREVIEWS: dict[str, dict] = {}


@app.post("/ingest/doc")
def ingest_doc(doc: Doc) -> dict:
    """Generate a lightweight preview for an ingested document."""

    interaction_id = str(uuid4())

    # very naive entity extraction
    persons = re.findall(r"\b[A-Z][a-z]+\s[A-Z][a-z]+\b", doc.text)
    orgs = re.findall(
        r"\b[A-Z][A-Za-z]*(?:\s[A-Z][A-Za-z]*)* (?:Corp|Corporation|Inc|LLC|Ltd)\b",
        doc.text,
    )
    commitments = [m.strip() for m in re.findall(r"will\s+([^\.]+)", doc.text)]

    preview = {
        "entities": {
            "persons": persons,
            "orgs": orgs,
            "commitments": commitments,
            "projects": [],
        },
        "relationships": [],
        "interaction": {
            "id": interaction_id,
            "type": "doc",
            "at": datetime.utcnow().isoformat(),
            "sentiment": "neutral",
            "summary": doc.text[:100],
            "source_uri": doc.source_uri,
        },
    }

    PREVIEWS[interaction_id] = preview
    return preview

