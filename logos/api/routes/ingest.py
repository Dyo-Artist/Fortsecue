"""Ingest and commit routes for LOGOS."""
from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from logos import app_state
from logos.core.pipeline_executor import PipelineContext, PipelineStageError, run_pipeline
from logos.feedback.store import append_feedback
from logos.graphio.neo4j_client import GraphUnavailable, get_client
from logos.models.bundles import FeedbackBundle, InteractionMeta, PreviewBundle
from logos.services.sync import build_graph_update_event, update_broadcaster

logger = logging.getLogger(__name__)

router = APIRouter()
legacy_router = APIRouter()


def _preview_payload(preview: PreviewBundle | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(preview, PreviewBundle):
        return preview.model_dump(mode="json")
    return dict(preview)


def _diff_values(before: Any, after: Any, path: str = "") -> list[dict[str, Any]]:
    if isinstance(before, Mapping) and isinstance(after, Mapping):
        changes: list[dict[str, Any]] = []
        keys = set(before.keys()) | set(after.keys())
        for key in sorted(keys, key=lambda value: str(value)):
            next_path = f"{path}.{key}" if path else str(key)
            if key not in before:
                changes.append({"path": next_path, "before": None, "after": after[key]})
            elif key not in after:
                changes.append({"path": next_path, "before": before[key], "after": None})
            else:
                changes.extend(_diff_values(before[key], after[key], next_path))
        return changes
    if isinstance(before, list) and isinstance(after, list):
        changes = []
        max_len = max(len(before), len(after))
        for index in range(max_len):
            next_path = f"{path}[{index}]" if path else f"[{index}]"
            if index >= len(before):
                changes.append({"path": next_path, "before": None, "after": after[index]})
            elif index >= len(after):
                changes.append({"path": next_path, "before": before[index], "after": None})
            else:
                changes.extend(_diff_values(before[index], after[index], next_path))
        return changes
    if before != after:
        resolved_path = path or "root"
        return [{"path": resolved_path, "before": before, "after": after}]
    return []


def _build_feedback_meta(
    interaction_id: str,
    committed_payload: Mapping[str, Any],
    fallback_payload: Mapping[str, Any] | None = None,
) -> InteractionMeta:
    meta = committed_payload.get("meta")
    if isinstance(meta, Mapping):
        return InteractionMeta.model_validate(meta)
    fallback = fallback_payload or {}
    interaction = committed_payload.get("interaction") or fallback.get("interaction") or {}
    return InteractionMeta(
        interaction_id=interaction_id,
        interaction_type=str(interaction.get("type") or "interaction"),
        source_uri=interaction.get("source_uri"),
        source_type="text",
        created_by=None,
    )


def _build_feedback_bundle(
    *,
    interaction_id: str,
    original_preview: PreviewBundle | Mapping[str, Any],
    committed_preview: PreviewBundle | Mapping[str, Any],
    user_id: str,
) -> FeedbackBundle:
    original_payload = _preview_payload(original_preview)
    committed_payload = _preview_payload(committed_preview)
    corrections = _diff_values(original_payload, committed_payload)
    meta = _build_feedback_meta(interaction_id, committed_payload, original_payload)
    processing_version = committed_payload.get("processing_version", "0.1")
    return FeedbackBundle(
        meta=meta,
        feedback="user_corrections",
        processing_version=processing_version,
        corrections=corrections,
        timestamp=datetime.now(timezone.utc),
        user_id=user_id,
    )


def _persist_feedback(bundle: FeedbackBundle) -> None:
    try:
        append_feedback(bundle)
    except Exception:  # pragma: no cover - avoid failing commit responses
        logger.exception(
            "feedback_persist_failed",
            extra={"interaction_id": bundle.meta.interaction_id},
        )


@router.post("/interactions/{interaction_id}/commit")
async def commit_interaction_api(
    interaction_id: str, edited_preview: PreviewBundle
) -> dict[str, object]:
    if edited_preview.meta.interaction_id != interaction_id:
        raise HTTPException(status_code=400, detail="interaction_id_mismatch")

    try:
        original_preview = app_state.STAGING_STORE.get_preview(interaction_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="preview_not_found") from None

    app_state.STAGING_STORE.save_preview(interaction_id, edited_preview)

    context = PipelineContext(
        request_id=interaction_id,
        user_id="api",
        context_data={
            "interaction_id": interaction_id,
            "graph_client_factory": get_client,
            "commit_time": datetime.now(timezone.utc),
            "graph_update_builder": build_graph_update_event,
        },
    )
    try:
        summary = run_pipeline("pipeline.interaction_commit", edited_preview, context)
    except PipelineStageError as exc:
        if isinstance(exc.cause, GraphUnavailable):
            app_state.STAGING_STORE.set_state(
                interaction_id, "failed", error_message="neo4j_unavailable"
            )
            raise HTTPException(status_code=503, detail="neo4j_unavailable") from None
        app_state.STAGING_STORE.set_state(interaction_id, "failed", error_message=str(exc))
        logger.exception("commit_failed", extra={"interaction_id": interaction_id})
        raise HTTPException(status_code=500, detail="commit_failed") from None
    except GraphUnavailable:
        app_state.STAGING_STORE.set_state(
            interaction_id, "failed", error_message="neo4j_unavailable"
        )
        raise HTTPException(status_code=503, detail="neo4j_unavailable") from None
    except Exception:
        app_state.STAGING_STORE.set_state(interaction_id, "failed", error_message="commit_failed")
        logger.exception("commit_failed", extra={"interaction_id": interaction_id})
        raise HTTPException(status_code=500, detail="commit_failed") from None

    graph_updates = context.context_data.get("graph_updates", [])
    for update in graph_updates:
        try:
            await update_broadcaster.broadcast(update)
        except Exception:  # pragma: no cover - avoid failing commit responses
            logger.exception("Failed to broadcast graph update for interaction %s", interaction_id)

    app_state.STAGING_STORE.set_state(interaction_id, "committed")
    app_state.PENDING_INTERACTIONS.pop(interaction_id, None)

    feedback_bundle = _build_feedback_bundle(
        interaction_id=interaction_id,
        original_preview=original_preview,
        committed_preview=edited_preview,
        user_id=context.user_id,
    )
    _persist_feedback(feedback_bundle)

    return summary


@legacy_router.post("/commit/{interaction_id}")
async def commit_interaction(interaction_id: str) -> dict[str, object]:
    preview = app_state.PENDING_INTERACTIONS.get(interaction_id)
    if preview is None:
        try:
            preview = app_state.STAGING_STORE.get_preview(interaction_id)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="interaction not found") from None

    try:
        context = PipelineContext(
            request_id=interaction_id,
            user_id="api",
            context_data={
                "interaction_id": interaction_id,
                "graph_client_factory": get_client,
                "commit_time": datetime.now(timezone.utc),
                "graph_update_builder": build_graph_update_event,
            },
        )
        summary = run_pipeline("pipeline.interaction_commit", preview, context)
    except PipelineStageError as exc:
        if isinstance(exc.cause, GraphUnavailable):
            return JSONResponse(status_code=503, content={"error": "neo4j_unavailable"})
        app_state.STAGING_STORE.set_state(interaction_id, "failed", error_message=str(exc))
        raise
    except GraphUnavailable:
        app_state.STAGING_STORE.set_state(
            interaction_id, "failed", error_message="neo4j_unavailable"
        )
        return JSONResponse(status_code=503, content={"error": "neo4j_unavailable"})
    except Exception:
        logger.exception("Failed to commit interaction %s", interaction_id)
        app_state.STAGING_STORE.set_state(interaction_id, "failed", error_message="commit_failed")
        raise HTTPException(status_code=500, detail="commit_failed")

    graph_updates = context.context_data.get("graph_updates", [])
    for update in graph_updates:
        try:
            await update_broadcaster.broadcast(update)
        except Exception:  # pragma: no cover - defensive guard to avoid failing commit responses
            logger.exception("Failed to broadcast graph update for interaction %s", interaction_id)

    app_state.PENDING_INTERACTIONS.pop(interaction_id, None)
    app_state.STAGING_STORE.set_state(interaction_id, "committed")

    feedback_bundle = _build_feedback_bundle(
        interaction_id=interaction_id,
        original_preview=preview,
        committed_preview=preview,
        user_id=context.user_id,
    )
    _persist_feedback(feedback_bundle)

    return summary

