"""NLP extraction module for LOGOS with optional Ollama integration."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List

import yaml
from jinja2 import Template, TemplateError

from logos.interfaces.ollama_client import OllamaError, call_llm

PROMPT_PATH = Path(__file__).resolve().parent.parent / "knowledgebase" / "prompts" / "extraction_interaction.yml"

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


class PromptConfigError(RuntimeError):
    """Raised when the extraction prompt is missing or cannot be rendered."""


def _load_extraction_prompt(prompt_path: Path | None = None) -> Dict[str, Any]:
    """Load the extraction prompt YAML configuration."""

    path = prompt_path or PROMPT_PATH

    if not path.exists():
        raise PromptConfigError(f"Prompt file not found at {path}")

    try:
        with path.open("r", encoding="utf-8") as file:
            data = yaml.safe_load(file) or {}
    except yaml.YAMLError as exc:  # pragma: no cover - yaml parser error handling
        raise PromptConfigError("Failed to parse extraction prompt YAML") from exc

    if not isinstance(data, dict):
        raise PromptConfigError("Extraction prompt YAML must be a mapping")

    return data


def _render_extraction_prompt(text: str, prompt_path: Path | None = None) -> str:
    """Render the extraction prompt template using Jinja2."""

    data = _load_extraction_prompt(prompt_path)

    template_text = data.get("template")
    if not isinstance(template_text, str) or not template_text.strip():
        raise PromptConfigError("Extraction prompt template is missing or empty")

    context = {
        "text": text,
        "stakeholder_type_list": "",
        "risk_category_list": "",
        "topic_list": "",
    }

    context_defaults = data.get("context_defaults")
    if isinstance(context_defaults, dict):
        context.update(context_defaults)

    try:
        return Template(template_text).render(**context)
    except TemplateError as exc:
        raise PromptConfigError("Failed to render extraction prompt template") from exc


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

    prompt = _render_extraction_prompt(text)

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
        except (OllamaError, json.JSONDecodeError, ValueError, KeyError, PromptConfigError):
            return _regex_extract_all(text)

    return _regex_extract_all(text)
