"""NLP extraction module for LOGOS with optional Ollama integration."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List

from logos.interfaces.ollama_client import OllamaError, call_llm

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


def _regex_extract_all(text: str) -> Dict[str, Any]:
    entities = _extract_entities(text)
    summary = text[:140]
    sentiment = 0.0
    return {
        "entities": entities,
        "relationships": [],
        "sentiment": sentiment,
        "summary": summary,
    }


def _ollama_enabled() -> bool:
    val = os.getenv("LOGOS_USE_OLLAMA", "").lower()
    return val in ("1", "true", "yes")


def _coerce_json_object(raw_text: str) -> Dict[str, Any]:
    """Parse JSON even when wrapped in extra text."""

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        pass

    start = raw_text.find("{")
    end = raw_text.rfind("}")

    if start != -1 and end != -1 and start < end:
        snippet = raw_text[start : end + 1]
        return json.loads(snippet)

    raise json.JSONDecodeError("Expecting value", raw_text, 0)


def _ollama_extract_all(text: str) -> Dict[str, Any]:
    """
    Ask the LLM to return a structured JSON extraction.

    Raises
    ------
    OllamaError
        If the LLM call fails.
    ValueError
        If the LLM response does not include expected keys.
    """

    prompt = (
        "You are LOGOS, an information extraction system. "
        "Given the input text, extract entities, relationships, sentiment, and summary. "
        "Respond with ONLY valid JSON following this schema and nothing else. "
        "Ensure all IDs are strings. Summary must be at most 140 characters.\n"
        "Input text:\n" + text + "\n"
        "Return JSON with this exact structure:\n"
        "{\n"
        "  \"entities\": {\n"
        "    \"persons\": [ { \"id\": \"p_...\", \"name\": \"...\", \"org_id\": \"o_acme\" } ],\n"
        "    \"orgs\": [ { \"id\": \"o_acme\", \"name\": \"Acme Pty Ltd\" } ],\n"
        "    \"projects\": [ { \"id\": \"pr_...\", \"name\": \"...\", \"status\": \"active\" } ],\n"
        "    \"contracts\": [ { \"id\": \"ct_...\", \"name\": \"...\", \"sap_id\": \"...\", \"value\": 12345.0, \"start_date\": \"YYYY-MM-DD\", \"end_date\": \"YYYY-MM-DD\" } ],\n"
        "    \"topics\": [ { \"id\": \"t_...\", \"name\": \"security\" } ],\n"
        "    \"commitments\": [ { \"id\": \"c_...\", \"text\": \"...\", \"person_id\": \"p_...\", \"due_date\": \"YYYY-MM-DD\", \"status\": \"open\", \"relates_to_project_id\": \"pr_...\", \"relates_to_contract_id\": \"ct_...\" } ]\n"
        "  },\n"
        "  \"relationships\": [ { \"src\": \"...\", \"dst\": \"...\", \"rel\": \"...\" } ],\n"
        "  \"sentiment\": 0.0,\n"
        "  \"summary\": \"Short summary here, max 140 characters.\"\n"
        "}"
    )

    raw_text = call_llm(prompt)
    data = _coerce_json_object(raw_text)

    if not isinstance(data, dict):
        raise ValueError("LLM response is not a JSON object")

    required_keys = {"entities", "relationships", "sentiment", "summary"}
    if not required_keys.issubset(data.keys()):
        raise ValueError("LLM response missing required keys")

    entities = data.get("entities")
    if not isinstance(entities, dict):
        raise ValueError("LLM entities must be a JSON object")

    for key in ("persons", "orgs", "projects", "contracts", "topics", "commitments"):
        entities.setdefault(key, [])

    data.setdefault("relationships", [])
    data.setdefault("sentiment", 0.0)
    data.setdefault("summary", text[:140])

    return data


def extract_all(text: str) -> Dict[str, Any]:
    """Extract entities, relationships, and sentiment from raw text."""

    if _ollama_enabled():
        try:
            return _ollama_extract_all(text)
        except (OllamaError, json.JSONDecodeError, ValueError, KeyError):
            return _regex_extract_all(text)

    return _regex_extract_all(text)
