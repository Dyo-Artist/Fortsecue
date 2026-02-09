"""Local feedback storage for LOGOS learning loops."""
from __future__ import annotations

import json
import os
from pathlib import Path

from logos.models.bundles import FeedbackBundle

DEFAULT_FEEDBACK_DIR = Path(os.getenv("LOGOS_FEEDBACK_DIR", ".logos/feedback"))


def append_feedback(bundle: FeedbackBundle, base_dir: Path | None = None) -> Path:
    """Append a feedback bundle to the JSONL store and return the file path."""
    target_dir = base_dir or DEFAULT_FEEDBACK_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / "feedback.jsonl"
    payload = bundle.model_dump(mode="json")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return path

