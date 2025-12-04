from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

from logos.graphio.neo4j_client import GraphUnavailable, get_client
from logos.graphio.upsert import InteractionBundle, upsert_interaction_bundle
from logos.nlp.extract import extract_all
from logos.normalise import build_interaction_bundle
from logos.normalise.resolution import resolve_preview_from_graph

from .bundles import ExtractionBundle, ParsedContentBundle, PipelineBundle, RawInputBundle


def _trace(context: Dict[str, Any], stage_name: str) -> None:
    """Append the executed stage to the context trace for observability."""

    trace: List[str] = context.setdefault("trace", [])  # type: ignore[assignment]
    trace.append(stage_name)


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
    }

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

    client = client_factory()

    def _tx(tx):
        upsert_interaction_bundle(tx, bundle, commit_time)

    client.run_in_tx(_tx)

    return {
        "status": "committed",
        "interaction_id": bundle.interaction.id,
        "counts": {
            "orgs": len(bundle.entities.orgs),
            "persons": len(bundle.entities.persons),
            "projects": len(bundle.entities.projects),
            "contracts": len(bundle.entities.contracts),
            "topics": len(bundle.entities.topics),
            "commitments": len(bundle.entities.commitments),
        },
    }

