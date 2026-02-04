"""Utilities for persisting preview bundles outside the staging index."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from logos.models.bundles import PreviewBundle
from logos.staging.store import LocalStagingStore

STAGING_DIR = Path(os.getenv("LOGOS_STAGING_DIR", ".logos/staging"))


def _preview_path(interaction_id: str) -> Path:
    return STAGING_DIR / f"{interaction_id}_preview.json"


def save_preview(interaction_id: str, preview: PreviewBundle) -> None:
    """Save the PreviewBundle to a JSON file in the staging directory."""
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    preview_path = _preview_path(interaction_id)
    preview_json = preview.model_dump(mode="json")
    preview_path.write_text(json.dumps(preview_json, indent=2), encoding="utf-8")


def load_preview(interaction_id: str) -> PreviewBundle:
    """Load a preview bundle from disk by interaction ID."""
    preview_path = _preview_path(interaction_id)
    if not preview_path.exists():
        raise FileNotFoundError(f"Preview not found for interaction {interaction_id}")
    data = json.loads(preview_path.read_text(encoding="utf-8"))
    return PreviewBundle.model_validate(data)


def mark_committed(interaction_id: str) -> None:
    """Mark an interaction as committed and clean up its preview file."""
    preview_path = _preview_path(interaction_id)
    if preview_path.exists():
        preview_path.unlink(missing_ok=True)
    LocalStagingStore().set_state(interaction_id, "committed")


def mark_failed(interaction_id: str, error_message: str = "") -> None:
    """Mark an interaction as failed in the staging store."""
    LocalStagingStore().set_state(interaction_id, "failed", error_message=error_message or None)


def prune_expired(max_age_days: int = 30) -> int:
    """Delete preview files older than ``max_age_days`` days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    removed = 0
    if not STAGING_DIR.exists():
        return removed
    for file in STAGING_DIR.glob("*_preview.json"):
        mtime = datetime.fromtimestamp(file.stat().st_mtime, timezone.utc)
        if mtime < cutoff:
            file.unlink(missing_ok=True)
            removed += 1
    return removed
