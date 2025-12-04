"""NLP extraction module for LOGOS with optional Ollama integration."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List

import yaml
from jinja2 import Template, TemplateError

from logos.interfaces.ollama_client import OllamaError, call_llm
from logos.model_tiers import TierConfigError, get_task_tier

PROMPT_PATH = Path(__file__).resolve().parent.parent / "knowledgebase" / "prompts" / "extraction_interaction.yml"
EXTRACTION_TASK_ID = "extraction_interaction"

LOGGER = logging.getLogger(__name__)
OBLIGATION_LEXICON_PATH = (
    Path(__file__).resolve().parent.parent
    / "knowledgebase"
    / "lexicons"
    / "obligation_phrases.yml"
)

_PERSON_PATTERN = re.compile(r"\b([A-Z][a-z]+ [A-Z][a-z]+)\b")
_ORG_PATTERN = re.compile(
    r"\b([A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*)*\s+(?:Pty Ltd|Pty|Ltd|LLC|Inc|Corporation|Corp|Company))\b"
)


def _extract_entities(text: str) -> Dict[str, List[str]]:
    persons = _PERSON_PATTERN.findall(text)
    orgs = _ORG_PATTERN.findall(text)
    commitments: List[str] = []
    for pattern in _COMMITMENT_PATTERNS:
        commitments.extend(pattern.findall(text))
    return {
        "persons": persons,
        "orgs": orgs,
        "projects": [],
        "contracts": [],
        "topics": [],
        "commitments": commitments,
        "issues": [],
        "risks": [],
        "outcomes": [],
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


class PromptConfigError(RuntimeError):
    """Raised when the extraction prompt is missing or cannot be rendered."""


class LexiconConfigError(RuntimeError):
    """Raised when the obligation phrase lexicon cannot be loaded."""


def _resolve_regex_flags(flags: Any) -> int:
    """Resolve YAML-provided regex flags into the Python re flags value."""

    if flags is None:
        return 0

    if isinstance(flags, str):
        flags = [flags]

    if not isinstance(flags, list):
        raise LexiconConfigError("Pattern flags must be a string or list of strings")

    flag_value = 0
    for flag_name in flags:
        if not isinstance(flag_name, str):
            raise LexiconConfigError("Pattern flags must be strings")

        flag_attr = getattr(re, flag_name, None)
        if not isinstance(flag_attr, int):
            raise LexiconConfigError(f"Unsupported regex flag: {flag_name}")

        flag_value |= flag_attr

    return flag_value


def _load_obligation_patterns(lexicon_path: Path | None = None) -> List[re.Pattern[str]]:
    """Load obligation regex patterns from the knowledgebase lexicon."""

    path = lexicon_path or OBLIGATION_LEXICON_PATH

    if not path.exists():
        raise LexiconConfigError(f"Obligation lexicon not found at {path}")

    try:
        with path.open("r", encoding="utf-8") as file:
            data = yaml.safe_load(file) or {}
    except yaml.YAMLError as exc:  # pragma: no cover - yaml parser error handling
        raise LexiconConfigError("Failed to parse obligation lexicon YAML") from exc

    patterns_config = data.get("patterns")
    if not isinstance(patterns_config, list):
        raise LexiconConfigError("Obligation lexicon must define a list under 'patterns'")

    compiled_patterns: List[re.Pattern[str]] = []
    for entry in patterns_config:
        if isinstance(entry, str):
            regex_text = entry
            flags_value = 0
        elif isinstance(entry, dict):
            regex_text = entry.get("regex")
            if not isinstance(regex_text, str):
                raise LexiconConfigError("Each pattern entry must define a regex string")
            flags_value = _resolve_regex_flags(entry.get("flags"))
        else:  # pragma: no cover - defensive branch
            raise LexiconConfigError("Each pattern entry must be a string or mapping")

        compiled_patterns.append(re.compile(regex_text, flags_value))

    return compiled_patterns


def _refresh_obligation_patterns(lexicon_path: Path | None = None) -> List[re.Pattern[str]]:
    """Reload obligation patterns, primarily used for testing or reconfiguration."""

    global _COMMITMENT_PATTERNS
    _COMMITMENT_PATTERNS = _load_obligation_patterns(lexicon_path)
    return _COMMITMENT_PATTERNS


try:
    _COMMITMENT_PATTERNS = _load_obligation_patterns()
except LexiconConfigError:
    _COMMITMENT_PATTERNS = []


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

    for key in (
        "persons",
        "orgs",
        "projects",
        "contracts",
        "topics",
        "commitments",
        "issues",
        "risks",
        "outcomes",
    ):
        entities.setdefault(key, [])

    data.setdefault("relationships", [])
    data.setdefault("sentiment", 0.0)
    data.setdefault("summary", text[:140])

    return data


def extract_all(text: str) -> Dict[str, Any]:
    """Extract entities, relationships, and sentiment from raw text."""
    tier_chain: List[str]
    try:
        selection = get_task_tier(EXTRACTION_TASK_ID)
        tier_chain = [selection.tier]
        if selection.fallback_tier and selection.fallback_tier not in tier_chain:
            tier_chain.append(selection.fallback_tier)
    except TierConfigError as exc:
        LOGGER.warning("Model tier config unavailable; defaulting to rule-only extraction: %s", exc)
        tier_chain = []

    if "rule_only" not in tier_chain:
        tier_chain.append("rule_only")

    for tier in tier_chain:
        if tier == "rule_only":
            return _regex_extract_all(text)
        if tier == "local_llm":
            try:
                return _ollama_extract_all(text)
            except (OllamaError, json.JSONDecodeError, ValueError, KeyError, PromptConfigError) as exc:
                LOGGER.info("Local LLM extraction failed; attempting fallback: %s", exc)
                continue
        if tier == "local_ml":
            LOGGER.info("Local ML extraction tier selected but not implemented; falling back")
            continue

        LOGGER.warning("Unknown extraction tier '%s'; falling back", tier)

    return _regex_extract_all(text)
