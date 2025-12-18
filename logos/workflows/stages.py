from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

from logos.graphio.neo4j_client import GraphUnavailable, get_client
from logos.graphio.upsert import InteractionBundle, upsert_interaction_bundle
from logos.memory import MemoryManager
from logos.graphio.upsert import InteractionBundle, SCHEMA_STORE, upsert_interaction_bundle
from logos.nlp.extract import extract_all
from logos.normalise import build_interaction_bundle
from logos.normalise.resolution import resolve_preview_from_graph
from logos.services.sync import build_graph_update_event
from logos.knowledgebase import KnowledgebaseStore, KnowledgebaseWriteError

from .bundles import ExtractionBundle, ParsedContentBundle, PipelineBundle, RawInputBundle

logger = logging.getLogger(__name__)


LOGGER = logging.getLogger(__name__)


def _trace(context: Dict[str, Any], stage_name: str) -> None:
    """Append the executed stage to the context trace for observability."""

    trace: List[str] = context.setdefault("trace", [])  # type: ignore[assignment]
    trace.append(stage_name)


def _get_memory_manager(context: Dict[str, Any]) -> MemoryManager:
    manager = context.get("memory_manager")
    if isinstance(manager, MemoryManager):
        return manager

    manager = MemoryManager()
    context["memory_manager"] = manager
    return manager


def require_raw_input(bundle: PipelineBundle | Dict[str, Any], context: Dict[str, Any] | None = None) -> RawInputBundle:
    """Ensure the pipeline starts with a RawInputBundle."""

    if context is None:
        context = {}
    _trace(context, "require_raw_input")

    if isinstance(bundle, RawInputBundle):
        return bundle
    if isinstance(bundle, dict):
        return RawInputBundle(**bundle)

    raise TypeError("Raw input bundle must be a mapping or RawInputBundle instance")


def tokenise_text(bundle: RawInputBundle | ParsedContentBundle, context: Dict[str, Any] | None = None) -> ParsedContentBundle:
    """Tokenise text content and preserve metadata."""

    if context is None:
        context = {}
    _trace(context, "tokenise_text")

    if isinstance(bundle, RawInputBundle):
        source_uri = bundle.source_uri
        metadata = dict(bundle.metadata)
        text = bundle.text
    elif isinstance(bundle, ParsedContentBundle):
        source_uri = bundle.source_uri
        metadata = dict(bundle.metadata)
        text = bundle.text
    else:  # pragma: no cover - defensive guard
        raise TypeError("tokenise_text expects a RawInputBundle or ParsedContentBundle")

    tokens = text.split()
    return ParsedContentBundle(text=text, tokens=tokens, source_uri=source_uri, metadata=metadata)


def build_preview_bundle(bundle: ParsedContentBundle | ExtractionBundle, context: Dict[str, Any] | None = None) -> ExtractionBundle:
    """Build a lightweight extraction bundle suitable for previews."""

    if context is None:
        context = {}
    _trace(context, "build_preview_bundle")

    if isinstance(bundle, ParsedContentBundle):
        text = bundle.text
        tokens = list(bundle.tokens)
        metadata = dict(bundle.metadata)
        source_uri = bundle.source_uri
    elif isinstance(bundle, ExtractionBundle):
        return bundle
    else:  # pragma: no cover - defensive guard
        raise TypeError("build_preview_bundle expects a ParsedContentBundle or ExtractionBundle")

    summary = " ".join(tokens[:10]) if tokens else text[:140]
    return ExtractionBundle(text=text, tokens=tokens, summary=summary, source_uri=source_uri, metadata=metadata)


def apply_extraction(
    bundle: ParsedContentBundle | RawInputBundle, context: Dict[str, Any] | None = None
) -> ExtractionBundle:
    """Run extraction to populate entities, relationships, and sentiment."""

    if context is None:
        context = {}
    _trace(context, "apply_extraction")

    if isinstance(bundle, ParsedContentBundle):
        text = bundle.text
        tokens = list(bundle.tokens)
        metadata = dict(bundle.metadata)
        source_uri = bundle.source_uri
    elif isinstance(bundle, RawInputBundle):
        text = bundle.text
        tokens = text.split()
        metadata = dict(bundle.metadata)
        source_uri = bundle.source_uri
    else:
        raise TypeError("apply_extraction expects a ParsedContentBundle or RawInputBundle")

    extraction = extract_all(text)
    summary = extraction.get("summary") if isinstance(extraction.get("summary"), str) else " ".join(tokens[:10])
    metadata.setdefault("type", context.get("interaction_type"))

    return ExtractionBundle(
        text=text,
        tokens=tokens,
        summary=summary,
        source_uri=source_uri,
        metadata=metadata,
        extraction=extraction,
    )


def sync_knowledgebase(bundle: ExtractionBundle, context: Dict[str, Any] | None = None) -> ExtractionBundle:
    """Persist newly learned patterns, concepts, or schema elements into the knowledgebase."""

    if context is None:
        context = {}
    _trace(context, "sync_knowledgebase")

    if not isinstance(bundle, ExtractionBundle):
        raise TypeError("Knowledgebase sync expects an ExtractionBundle")

    updater = context.get("knowledge_updater")
    if not isinstance(updater, KnowledgebaseStore):
        base_path = context.get("knowledgebase_path")
        actor = context.get("actor") or context.get("user") or "system"
        updater = KnowledgebaseStore(base_path=base_path, actor=str(actor))

    updates: dict[str, list[str]] = {"lexicon_updates": [], "concept_updates": [], "schema_updates": []}
    try:
        updates = updater.learn_from_extraction(bundle.extraction, source_uri=bundle.source_uri)

        schema_updates = context.get("schema_updates") if isinstance(context.get("schema_updates"), dict) else {}
        for node_type in schema_updates.get("node_types", []):
            if isinstance(node_type, dict):
                added = updater.add_node_type(node_type, reason="Schema evolution from pipeline")
                if added:
                    updates.setdefault("schema_updates", []).append(node_type.get("id") or node_type.get("label", ""))
        for rel_type in schema_updates.get("relationship_types", []):
            if isinstance(rel_type, dict):
                added = updater.add_relationship_type(rel_type, reason="Schema evolution from pipeline")
                if added:
                    updates.setdefault("schema_updates", []).append(rel_type.get("type") or rel_type.get("rel", ""))
    except KnowledgebaseWriteError as exc:
        LOGGER.warning("Knowledgebase sync failed: %s", exc)

    context["knowledgebase_updates"] = updates
    return bundle


def build_preview_payload(bundle: ExtractionBundle, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Construct and optionally persist a preview payload for an interaction."""

    if context is None:
        context = {}
    _trace(context, "build_preview_payload")

    if not isinstance(bundle, ExtractionBundle):
        raise TypeError("build_preview_payload expects an ExtractionBundle")

    interaction_id = context.get("interaction_id") or uuid4().hex
    type_ = context.get("interaction_type") or bundle.metadata.get("type") or "interaction"
    at_raw = context.get("interaction_at")
    if isinstance(at_raw, datetime):
        at_val = at_raw.astimezone(timezone.utc).isoformat()
    elif isinstance(at_raw, str):
        at_val = at_raw
    else:
        at_val = datetime.now(timezone.utc).isoformat()

    source_uri = bundle.source_uri or context.get("source_uri") or ""
    extraction_data = dict(bundle.extraction)
    extraction_data.setdefault("summary", bundle.summary)
    extraction_data.setdefault("sentiment", extraction_data.get("sentiment"))
    reasoning = extraction_data.get("reasoning", []) if isinstance(extraction_data.get("reasoning"), list) else []

    metadata = {"type": type_, "at": at_val, "source_uri": source_uri}
    preview = {
        "interaction": {
            "id": interaction_id,
            **metadata,
            "sentiment": extraction_data.get("sentiment"),
            "summary": extraction_data.get("summary", bundle.summary),
        },
        "entities": extraction_data.get("entities", {}),
        "relationships": extraction_data.get("relationships", []),
        "reasoning": reasoning,
    }

    if reasoning:
        manager = _get_memory_manager(context)
        importance = float(context.get("reasoning_importance", 0.0)) if context else 0.0
        short_item = manager.record_short_term(
            str(interaction_id),
            "reasoning_trace",
            reasoning,
            importance=importance,
            tags=("reasoning", type_),
            metadata={"source_uri": source_uri, "summary": extraction_data.get("summary", bundle.summary)},
        )
        if context.get("persist_reasoning") or context.get("retain_reasoning"):
            manager.promote_short_term_to_mid_term(
                str(interaction_id),
                short_item.id,
                pinned=bool(context.get("pin_reasoning", False)),
                importance=importance,
            )

    persist_fn = context.get("persist_preview")
    if callable(persist_fn):
        return persist_fn(interaction_id, metadata, extraction_data)

    return preview


def require_preview_payload(bundle: Dict[str, Any] | Any, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Ensure commit pipeline begins with a preview mapping."""

    if context is None:
        context = {}
    _trace(context, "require_preview_payload")

    if isinstance(bundle, dict):
        return bundle

    raise TypeError("Commit pipeline expects a preview mapping")


def resolve_entities_from_graph(bundle: Dict[str, Any], context: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Resolve preview entities to canonical graph IDs before upsert."""

    if context is None:
        context = {}
    _trace(context, "resolve_entities_from_graph")

    if not isinstance(bundle, dict):
        raise TypeError("Entity resolution expects a preview mapping")

    client_factory = context.get("graph_client_factory") or get_client

    try:
        return resolve_preview_from_graph(bundle, client_factory=client_factory)
    except GraphUnavailable:
        return bundle


def build_interaction_bundle_stage(bundle: Dict[str, Any], context: Dict[str, Any] | None = None) -> InteractionBundle:
    """Convert a preview payload into an InteractionBundle for upsert."""

    if context is None:
        context = {}
    _trace(context, "build_interaction_bundle_stage")

    if not isinstance(bundle, dict):
        raise TypeError("Interaction bundle stage expects a preview mapping")

    interaction_id = context.get("interaction_id") or bundle.get("interaction", {}).get("id")
    if not interaction_id:
        raise ValueError("Interaction id is required to build the bundle")

    return build_interaction_bundle(interaction_id, bundle)


def upsert_interaction_bundle_stage(
    bundle: InteractionBundle, context: Dict[str, Any] | None = None
) -> Dict[str, Any]:
    """Upsert an interaction bundle into Neo4j."""

    if context is None:
        context = {}
    _trace(context, "upsert_interaction_bundle_stage")

    if not isinstance(bundle, InteractionBundle):
        raise TypeError("Upsert stage expects an InteractionBundle")

    client_factory = context.get("graph_client_factory") or get_client
    commit_time = context.get("commit_time") or datetime.now(timezone.utc)
    schema_store = context.get("schema_store", SCHEMA_STORE)

    client = client_factory()

    def _tx(tx):
        upsert_interaction_bundle(tx, bundle, commit_time, schema_store=schema_store)

    client.run_in_tx(_tx)

    try:
        update_builder = context.get("graph_update_builder", build_graph_update_event)
        if callable(update_builder):
            graph_updates = context.setdefault("graph_updates", [])
            graph_updates.append(update_builder(bundle, commit_time))
    except Exception:  # pragma: no cover - defensive guard to avoid breaking commit flow
        logger.exception("Failed to build graph update event for interaction %s", bundle.interaction.id)

    return {
        "status": "committed",
        "interaction_id": bundle.interaction.id,
        "counts": _summarise_counts(bundle),
    }


def ensure_memory_manager(bundle: Any, context: Dict[str, Any] | None = None) -> MemoryManager:
    """Guarantee a MemoryManager is available in the pipeline context."""

    if context is None:
        context = {}
    _trace(context, "ensure_memory_manager")

    if isinstance(bundle, MemoryManager):
        context.setdefault("memory_manager", bundle)
        return bundle

    return _get_memory_manager(context)


def consolidate_memory_stage(manager: MemoryManager, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Run consolidation to decay or promote memory entries."""

    if context is None:
        context = {}
    _trace(context, "consolidate_memory_stage")

    if not isinstance(manager, MemoryManager):
        raise TypeError("consolidate_memory_stage expects a MemoryManager instance")

    session_id = context.get("interaction_id")
    session_key = str(session_id) if session_id is not None else None
    now_candidate = context.get("now")
    now = now_candidate if isinstance(now_candidate, datetime) else None
    persist_candidate = context.get("persist_long_term")
    persist_fn = persist_candidate if callable(persist_candidate) else None

    return manager.consolidate(session_id=session_key, now=now, persist_fn=persist_fn)
def _summarise_counts(bundle: InteractionBundle) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for node in bundle.nodes:
        counts[node.label.lower() + "s"] = counts.get(node.label.lower() + "s", 0) + 1
    return counts
