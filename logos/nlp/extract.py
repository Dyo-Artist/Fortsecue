"""NLP extraction module for LOGOS with optional Ollama integration."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

import yaml
from jinja2 import Template, TemplateError

from logos.interfaces.ollama_client import OllamaError, call_llm
from logos.model_tiers import TierConfigError, get_task_tier
from logos.knowledgebase import KnowledgebaseStore, KnowledgebaseWriteError

PROMPT_PATH = Path(__file__).resolve().parent.parent / "knowledgebase" / "prompts" / "extraction_interaction.yml"
DOMAIN_PROFILES_DIR = Path(__file__).resolve().parent.parent / "knowledgebase" / "domain_profiles"
SCHEMA_NODE_TYPES_PATH = Path(__file__).resolve().parent.parent / "knowledgebase" / "schema" / "node_types.yml"
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


def _load_yaml(path: Path) -> Any:
    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def _to_snake(text: str) -> str:
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", text).replace("-", "_").lower()
    return snake


def _schema_entity_keys(schema_path: Path | None = None) -> List[str]:
    """Return pluralised entity keys derived from the schema node types."""

    path = schema_path or SCHEMA_NODE_TYPES_PATH
    data = _load_yaml(path)
    node_types = data.get("node_types") if isinstance(data, Mapping) else {}
    keys: List[str] = []

    if isinstance(node_types, Mapping):
        for label in node_types.keys():
            if not isinstance(label, str):
                continue
            snake = _to_snake(label)
            plural = snake if snake.endswith("s") else f"{snake}s"
            keys.append(plural)

    return sorted(set(keys))


def _blank_entity_map(schema_path: Path | None = None) -> Dict[str, list]:
    return {key: [] for key in _schema_entity_keys(schema_path)}


def _extract_entities(text: str) -> Dict[str, List[str]]:
    entities = _blank_entity_map()
    if "persons" in entities:
        entities["persons"] = _PERSON_PATTERN.findall(text)
    if "orgs" in entities:
        entities["orgs"] = _ORG_PATTERN.findall(text)
    if "commitments" in entities:
        commitments: List[str] = []
        for pattern in _COMMITMENT_PATTERNS:
            commitments.extend(pattern.findall(text))
        entities["commitments"] = commitments

    return entities


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


def _load_domain_profile(profile_id: str | None = None) -> Mapping[str, Any]:
    profile_name = f"{profile_id}.yml" if profile_id else "stakeholder_engagement.yml"
    profile_path = DOMAIN_PROFILES_DIR / profile_name
    data = _load_yaml(profile_path)
    return data if isinstance(data, Mapping) else {}


def _load_named_items(path: Path, key: str) -> List[str]:
    data = _load_yaml(path)
    if not isinstance(data, Mapping):
        return []

    entries = data.get(key)
    results: List[str] = []
    if isinstance(entries, Iterable):
        for entry in entries:
            if isinstance(entry, Mapping):
                name = entry.get("name") or entry.get("id")
                if name:
                    results.append(str(name))
            elif isinstance(entry, str):
                results.append(entry)
    return results


def _prompt_context_from_profile(prompt_config: Mapping[str, Any]) -> Dict[str, str]:
    profile_id = prompt_config.get("domain_profile") if isinstance(prompt_config, Mapping) else None
    profile = _load_domain_profile(str(profile_id) if profile_id else None)
    base = DOMAIN_PROFILES_DIR

    def _resolve(relative: str | None) -> Path | None:
        if not relative:
            return None
        return (base / relative).resolve()

    concept_files = profile.get("concept_files") if isinstance(profile.get("concept_files"), Mapping) else {}
    topics_config = profile.get("topics") if isinstance(profile.get("topics"), Mapping) else {}

    stakeholder_types = _load_named_items(
        _resolve(concept_files.get("stakeholder_types")) or Path(),
        "stakeholder_types",
    )
    risk_categories = _load_named_items(
        _resolve(concept_files.get("risk_categories")) or Path(),
        "risk_categories",
    )
    topics_path = _resolve(topics_config.get("file"))
    topics = _load_named_items(topics_path or Path(), "topics") if topics_path else []

    return {
        "stakeholder_type_list": ", ".join(stakeholder_types),
        "risk_category_list": ", ".join(risk_categories),
        "topic_list": ", ".join(topics),
    }


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

    context.update(_prompt_context_from_profile(data))

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


def _normalise_llm_entities(entities: Mapping[str, Any]) -> Dict[str, Any]:
    normalised = _blank_entity_map()
    for key, value in entities.items():
        if key not in normalised and isinstance(key, str):
            normalised[key] = []
        if isinstance(value, list):
            normalised[key] = value
    return normalised


def _ollama_extract_all(text: str) -> Dict[str, Any]:
    """Ask the LLM to return a structured JSON extraction using the YAML prompt."""

    prompt = _render_extraction_prompt(text)

    raw_text = call_llm(prompt)
    data = _coerce_json_object(raw_text)

    if not isinstance(data, dict):
        raise ValueError("LLM response is not a JSON object")

    interaction = data.get("interaction_proposal") or data.get("interaction")
    entities_raw = data.get("entities")

    if not isinstance(entities_raw, Mapping):
        raise ValueError("LLM entities must be a JSON object")

    summary = None
    sentiment = None
    if isinstance(interaction, Mapping):
        summary = interaction.get("summary") or interaction.get("subject")
        sentiment = (
            interaction.get("sentiment_score")
            if isinstance(interaction.get("sentiment_score"), (int, float))
            else interaction.get("sentiment")
        )

    relationships = data.get("relationships") if isinstance(data.get("relationships"), list) else []
    entities = _normalise_llm_entities(entities_raw)

    return {
        "interaction": interaction if isinstance(interaction, Mapping) else {},
        "entities": entities,
        "relationships": relationships,
        "sentiment": float(sentiment) if isinstance(sentiment, (int, float)) else 0.0,
        "summary": str(summary) if isinstance(summary, str) and summary else text[:140],
    }


def extract_all(
    text: str,
    *,
    knowledge_updater: KnowledgebaseStore | None = None,
    learning_signals: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Extract entities, relationships, and sentiment from raw text."""
    tier_chain: List[str]
    result: Dict[str, Any] | None = None
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
            result = _regex_extract_all(text)
            break
        if tier == "local_llm":
            try:
                result = _ollama_extract_all(text)
                break
            except (OllamaError, json.JSONDecodeError, ValueError, KeyError, PromptConfigError) as exc:
                LOGGER.info("Local LLM extraction failed; attempting fallback: %s", exc)
                continue
        if tier == "local_ml":
            LOGGER.info("Local ML extraction tier selected but not implemented; falling back")
            continue

        LOGGER.warning("Unknown extraction tier '%s'; falling back", tier)

    if result is None:
        result = _regex_extract_all(text)

    if knowledge_updater is not None:
        try:
            knowledge_updater.learn_from_extraction(result)
            if learning_signals:
                knowledge_updater.apply_learning_signals(learning_signals)
        except KnowledgebaseWriteError as exc:
            LOGGER.warning("Unable to persist learned knowledge: %s", exc)

    return result
