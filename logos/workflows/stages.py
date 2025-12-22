from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping
from uuid import uuid4

from logos.graphio.neo4j_client import GraphUnavailable, get_client
from logos.memory import MemoryItem, MemoryManager
from logos.graphio.upsert import InteractionBundle, SCHEMA_STORE, upsert_interaction_bundle
from logos.nlp.extract import extract_all
from logos.normalise import build_interaction_bundle
from logos.normalise.resolution import resolve_preview_from_graph
from logos.services.sync import build_graph_update_event
from logos.knowledgebase import KnowledgebaseStore, KnowledgebaseWriteError
from logos.models.bundles import (
    InteractionMeta,
    InteractionSnapshot,
    EntityMention,
    PreviewBundle,
    PreviewEntity,
    Relationship,
)

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


def _merge_updates(target: Dict[str, list[str]], incoming: Mapping[str, Any] | None) -> Dict[str, list[str]]:
    """Combine learning update dictionaries while preserving list semantics."""

    if not isinstance(incoming, Mapping):
        return target

    for key, value in incoming.items():
        if isinstance(value, list):
            target.setdefault(key, []).extend(value)

    return target


def _coerce_meta(meta_candidate: Any, context: Dict[str, Any]) -> InteractionMeta:
    """Build or coerce InteractionMeta from incoming payload or context."""

    if isinstance(meta_candidate, InteractionMeta):
        return meta_candidate

    if isinstance(meta_candidate, Mapping):
        return InteractionMeta.model_validate(meta_candidate)

    now = datetime.now(timezone.utc)
    created_by = context.get("actor") or context.get("user") or context.get("created_by")
    return InteractionMeta(
        interaction_id=str(context.get("interaction_id") or uuid4().hex),
        interaction_type=str(context.get("interaction_type") or context.get("type") or "interaction"),
        interaction_at=context.get("interaction_at") or now,
        source_uri=context.get("source_uri"),
        source_type=str(context.get("source_type") or "text"),
        created_by=str(created_by) if created_by is not None else None,
        received_at=context.get("received_at") or now,
        project_id=context.get("project_id"),
        contract_id=context.get("contract_id"),
    )


def require_raw_input(bundle: PipelineBundle | Dict[str, Any], context: Dict[str, Any] | None = None) -> RawInputBundle:
    """Ensure the pipeline starts with a RawInputBundle."""

    if context is None:
        context = {}
    _trace(context, "require_raw_input")

    if isinstance(bundle, RawInputBundle):
        meta = _coerce_meta(getattr(bundle, "meta", None), context)
        return RawInputBundle(
            meta=meta,
            raw_text=bundle.raw_text,
            raw_file_path=bundle.raw_file_path,
            content_hash=bundle.content_hash,
            metadata=dict(getattr(bundle, "metadata", {})),
        )
    if isinstance(bundle, dict):
        meta = _coerce_meta(bundle.get("meta"), context)
        return RawInputBundle(
            meta=meta,
            raw_text=bundle.get("raw_text") or bundle.get("text"),
            raw_file_path=bundle.get("raw_file_path"),
            content_hash=bundle.get("content_hash"),
            metadata=bundle.get("metadata", {}),
        )

    raise TypeError("Raw input bundle must be a mapping or RawInputBundle instance")


def tokenise_text(bundle: RawInputBundle | ParsedContentBundle, context: Dict[str, Any] | None = None) -> ParsedContentBundle:
    """Tokenise text content and preserve metadata."""

    if context is None:
        context = {}
    _trace(context, "tokenise_text")

    if isinstance(bundle, RawInputBundle):
        meta = bundle.meta
        metadata = dict(bundle.metadata)
        text = bundle.text
    elif isinstance(bundle, ParsedContentBundle):
        meta = bundle.meta
        metadata = dict(bundle.metadata)
        text = bundle.text
    else:  # pragma: no cover - defensive guard
        raise TypeError("tokenise_text expects a RawInputBundle or ParsedContentBundle")

    tokens = text.split()
    return ParsedContentBundle(meta=meta, text=text, tokens=tokens, metadata=metadata)


def build_preview_bundle(bundle: ParsedContentBundle | ExtractionBundle, context: Dict[str, Any] | None = None) -> ExtractionBundle:
    """Build a lightweight extraction bundle suitable for previews."""

    if context is None:
        context = {}
    _trace(context, "build_preview_bundle")

    if isinstance(bundle, ParsedContentBundle):
        text = bundle.text
        tokens = list(bundle.tokens)
        metadata = dict(bundle.metadata)
        meta = bundle.meta
    elif isinstance(bundle, ExtractionBundle):
        return bundle
    else:  # pragma: no cover - defensive guard
        raise TypeError("build_preview_bundle expects a ParsedContentBundle or ExtractionBundle")

    summary = " ".join(tokens[:10]) if tokens else text[:140]
    return ExtractionBundle(meta=meta, text=text, tokens=tokens, summary=summary, metadata=metadata)


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
        meta = bundle.meta
    elif isinstance(bundle, RawInputBundle):
        text = bundle.text
        tokens = text.split()
        metadata = dict(bundle.metadata)
        meta = bundle.meta
    else:
        raise TypeError("apply_extraction expects a ParsedContentBundle or RawInputBundle")

    extraction = extract_all(text)
    summary = extraction.get("summary") if isinstance(extraction.get("summary"), str) else " ".join(tokens[:10])
    metadata.setdefault("type", context.get("interaction_type"))

    entities_raw = extraction.get("entities") if isinstance(extraction, Mapping) else {}
    relationships_raw = extraction.get("relationships") if isinstance(extraction, Mapping) else []
    metrics = extraction.get("metrics") if isinstance(extraction, Mapping) else {}

    entities: Dict[str, list[EntityMention]] = {}
    if isinstance(entities_raw, Mapping):
        for key, value in entities_raw.items():
            if isinstance(value, list):
                normalised: list[EntityMention] = []
                for entry in value:
                    if isinstance(entry, EntityMention):
                        normalised.append(entry)
                    elif isinstance(entry, Mapping):
                        normalised.append(EntityMention.model_validate(entry))
                    else:
                        normalised.append(EntityMention(temp_id=str(entry), name=str(entry)))
                entities[key] = normalised

    relationships: list[Relationship] = []
    if isinstance(relationships_raw, list):
        for rel in relationships_raw:
            if isinstance(rel, Mapping):
                relationships.append(Relationship.model_validate(rel))

    metrics = metrics if isinstance(metrics, Mapping) else {}

    return ExtractionBundle(
        meta=meta,
        text=text,
        tokens=tokens,
        summary=summary,
        metadata=metadata,
        extraction=extraction if isinstance(extraction, Mapping) else {},
        entities=entities,
        relationships=relationships,
        metrics=dict(metrics),
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

    updates: dict[str, list[str]] = {
        "lexicon_updates": [],
        "concept_updates": [],
        "schema_updates": [],
        "sentiment_updates": [],
        "learning_signals": [],
    }
    try:
        updates = updater.learn_from_extraction(bundle.extraction, source_uri=bundle.meta.source_uri)

        schema_updates = context.get("schema_updates") if isinstance(context.get("schema_updates"), dict) else {}

        learning_signals: dict[str, Any] = {}
        if schema_updates:
            learning_signals["schema_suggestions"] = schema_updates

        for source in (getattr(bundle, "metadata", None), context):
            if isinstance(source, Mapping):
                raw_signals = source.get("learning_signals")
                if isinstance(raw_signals, Mapping):
                    for key, value in raw_signals.items():
                        if isinstance(value, list) or isinstance(value, Mapping):
                            existing = learning_signals.get(key)
                            if isinstance(existing, list) and isinstance(value, list):
                                learning_signals[key] = existing + value
                            elif isinstance(existing, Mapping) and isinstance(value, Mapping):
                                merged = dict(existing)
                                for sig_key, sig_value in value.items():
                                    if sig_key in merged and isinstance(merged[sig_key], list) and isinstance(sig_value, list):
                                        merged[sig_key] = merged[sig_key] + sig_value
                                    else:
                                        merged[sig_key] = sig_value
                                learning_signals[key] = merged
                            else:
                                learning_signals[key] = value
                        else:
                            learning_signals[key] = value

        signal_updates = updater.apply_learning_signals(learning_signals)
        updates = _merge_updates(updates, signal_updates)
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

    source_uri = bundle.meta.source_uri or context.get("source_uri") or ""
    extraction_data = dict(bundle.extraction)
    extraction_data.setdefault("summary", bundle.summary)
    extraction_data.setdefault("sentiment", extraction_data.get("sentiment") or bundle.metrics.get("sentiment"))
    reasoning = extraction_data.get("reasoning", []) if isinstance(extraction_data.get("reasoning"), list) else []

    entities_raw = extraction_data.get("entities") if isinstance(extraction_data, Mapping) else None
    entities = bundle.entities if entities_raw is None else entities_raw
    relationships_raw = extraction_data.get("relationships") if isinstance(extraction_data, Mapping) else None
    relationships = bundle.relationships if relationships_raw is None else relationships_raw

    preview_entities: Dict[str, List[PreviewEntity]] = {}
    if isinstance(entities, Mapping):
        for key, value in entities.items():
            if isinstance(value, list):
                normalised_entities: List[PreviewEntity] = []
                for item in value:
                    if isinstance(item, PreviewEntity):
                        normalised_entities.append(item)
                    elif isinstance(item, Mapping):
                        normalised_entities.append(PreviewEntity.model_validate(item))
                    else:
                        normalised_entities.append(
                            PreviewEntity(temp_id=str(item), name=str(item), is_new=True)
                        )
                preview_entities[key] = normalised_entities

    preview_relationships: List[Relationship] = []
    if isinstance(relationships, list):
        for rel in relationships:
            if isinstance(rel, Relationship):
                preview_relationships.append(rel)
            elif isinstance(rel, Mapping):
                preview_relationships.append(Relationship.model_validate(rel))

    interaction_snapshot = InteractionSnapshot(
        summary=extraction_data.get("summary", bundle.summary),
        at=at_val,
        sentiment=extraction_data.get("sentiment"),
        subject=context.get("subject"),
    )

    preview_bundle = PreviewBundle(
        meta=bundle.meta,
        interaction=interaction_snapshot,
        entities=preview_entities,
        relationships=preview_relationships,
        ready=True,
    )

    preview = preview_bundle.model_dump()
    preview["reasoning"] = reasoning
    preview.setdefault("interaction", {})
    preview["interaction"].update({"id": interaction_id, "type": type_, "source_uri": source_uri})

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

    manager = _get_memory_manager(context)
    manager.record_short_term(
        str(interaction_id),
        "preview_bundle",
        {
            "interaction": preview.get("interaction", {}),
            "entities": preview.get("entities", {}),
            "relationships": preview.get("relationships", []),
        },
        importance=float(context.get("preview_importance", 0.5)),
        tags=("preview", type_),
        metadata={"source_uri": source_uri},
    )
    manager.update_session_summary(str(interaction_id), preview)

    persist_fn = context.get("persist_preview")
    if callable(persist_fn):
        return persist_fn(
            interaction_id,
            {"type": type_, "at": at_val, "source_uri": source_uri},
            extraction_data,
        )

    return preview


def require_preview_payload(bundle: Dict[str, Any] | Any, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Ensure commit pipeline begins with a preview mapping."""

    if context is None:
        context = {}
    _trace(context, "require_preview_payload")

    if isinstance(bundle, PreviewBundle):
        return bundle.model_dump()
    if isinstance(bundle, dict):
        return bundle

    raise TypeError("Commit pipeline expects a preview mapping")


def capture_preview_memory(bundle: Dict[str, Any], context: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Project the preview payload into short- and mid-term memory for the session."""

    if context is None:
        context = {}
    _trace(context, "capture_preview_memory")

    if isinstance(bundle, PreviewBundle):
        preview_payload = bundle.model_dump()
    elif isinstance(bundle, dict):
        preview_payload = bundle
    else:
        raise TypeError("capture_preview_memory expects a preview mapping")

    session_id = str(context.get("interaction_id") or preview_payload.get("interaction", {}).get("id") or uuid4().hex)
    context.setdefault("interaction_id", session_id)
    manager = _get_memory_manager(context)

    preview_snapshot = {
        "interaction": preview_payload.get("interaction", {}),
        "entities": preview_payload.get("entities", {}),
        "relationships": preview_payload.get("relationships", []),
    }
    manager.record_short_term(
        session_id,
        "preview_bundle",
        preview_snapshot,
        importance=float(context.get("preview_importance", 0.5)),
        tags=("preview", preview_snapshot.get("interaction", {}).get("type", "")),
        metadata={"source_uri": preview_snapshot.get("interaction", {}).get("source_uri")},
    )
    manager.update_session_summary(session_id, bundle)
    return bundle


def resolve_entities_from_graph(bundle: Dict[str, Any] | PreviewBundle, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Resolve preview entities to canonical graph IDs before upsert."""

    if context is None:
        context = {}
    _trace(context, "resolve_entities_from_graph")

    if isinstance(bundle, PreviewBundle):
        payload = bundle.model_dump()
    elif isinstance(bundle, dict):
        payload = bundle
    else:
        raise TypeError("Entity resolution expects a preview mapping")

    client_factory = context.get("graph_client_factory") or get_client

    try:
        return resolve_preview_from_graph(payload, client_factory=client_factory)
    except GraphUnavailable:
        return payload


def build_interaction_bundle_stage(bundle: Dict[str, Any] | PreviewBundle, context: Dict[str, Any] | None = None) -> InteractionBundle:
    """Convert a preview payload into an InteractionBundle for upsert."""

    if context is None:
        context = {}
    _trace(context, "build_interaction_bundle_stage")

    if isinstance(bundle, PreviewBundle):
        payload = bundle.model_dump()
    elif isinstance(bundle, dict):
        payload = bundle
    else:
        raise TypeError("Interaction bundle stage expects a preview mapping")

    interaction_id = context.get("interaction_id") or payload.get("interaction", {}).get("id")
    if not interaction_id:
        raise ValueError("Interaction id is required to build the bundle")

    return build_interaction_bundle(interaction_id, payload)


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


def persist_session_memory(bundle: Dict[str, Any], context: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Persist mid-term session context into the knowledgebase as long-term memory."""

    if context is None:
        context = {}
    _trace(context, "persist_session_memory")

    manager = _get_memory_manager(context)
    session_id = str(context.get("interaction_id") or bundle.get("interaction_id") or "")
    kb_store = context.get("knowledge_updater")
    if not isinstance(kb_store, KnowledgebaseStore):
        kb_store = KnowledgebaseStore(
            base_path=context.get("knowledgebase_path"), actor=str(context.get("actor") or context.get("user") or "system")
        )

    def _persist(item: MemoryItem, payload: Dict[str, Any]) -> None:
        history = payload.get("metadata", {}).get("history", []) if isinstance(payload.get("metadata"), Mapping) else []
        kb_store.record_session_memory(
            session_id or payload.get("key", "session"),
            payload.get("content", ""),
            interactions=history if isinstance(history, list) else [],
            reason=f"Persisted session summary for {session_id or 'interaction'}",
        )

    manager.consolidate(session_id=session_id, persist_fn=_persist)
    return bundle


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
