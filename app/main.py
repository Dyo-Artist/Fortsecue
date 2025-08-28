from __future__ import annotations

from datetime import datetime
from typing import Dict, List
from uuid import uuid4

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

# In-memory storage for previews
PREVIEWS: Dict[str, dict] = {}


class IngestDoc(BaseModel):
    """Request model for document ingestion."""

    source_uri: str
    text: str


@app.post("/ingest/doc")
def ingest_doc(doc: IngestDoc) -> dict:
    """Generate a preview for an ingested document."""
    interaction_id = str(uuid4())
    persons = _extract_persons(doc.text)
    orgs = _extract_orgs(doc.text)
    commitments = _extract_commitments(doc.text)
    projects: List[str] = []

    preview = {
        "entities": {
            "persons": persons,
            "orgs": orgs,
            "commitments": commitments,
            "projects": projects,
        },
        "relationships": _build_relationships(persons, orgs),
        "interaction": {
            "id": interaction_id,
            "type": "document",
            "at": datetime.utcnow().isoformat(),
            "sentiment": 0,
            "summary": doc.text[:100],
            "source_uri": doc.source_uri,
        },
    }
    PREVIEWS[interaction_id] = preview
    return preview


def _extract_persons(text: str) -> List[str]:
    """Very naive person extractor based on capitalised words.

    Tokens that are followed by ``Corp`` or ``Inc`` are assumed to be part of
    an organisation name and therefore excluded.
    """
    tokens = text.split()
    persons: List[str] = []
    for i, tok in enumerate(tokens):
        if not tok.istitle():
            continue
        if i + 1 < len(tokens) and tokens[i + 1] in {"Corp", "Inc"}:
            continue
        persons.append(tok)
    return persons


def _extract_orgs(text: str) -> List[str]:
    """Naive organisation extractor for words ending with Corp or Inc."""
    tokens = text.split()
    return [
        " ".join(tokens[i : i + 2])
        for i in range(len(tokens) - 1)
        if tokens[i + 1] in {"Corp", "Inc"}
    ]


def _extract_commitments(text: str) -> List[str]:
    """Extract sentences containing 'commit'."""
    commitments: List[str] = []
    for sent in text.split("."):
        if "commit" in sent.lower():
            commitments.append(sent.strip())
    return commitments


def _build_relationships(persons: List[str], orgs: List[str]) -> List[dict]:
    """Connect each person to each organisation as an affiliation."""
    relationships: List[dict] = []
    for p in persons:
        for o in orgs:
            relationships.append({"type": "affiliation", "from": p, "to": o})
    return relationships
