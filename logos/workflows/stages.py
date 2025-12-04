from __future__ import annotations

from typing import Any, Dict, List

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

