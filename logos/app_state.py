"""Shared application state for LOGOS routes and pipelines."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

from logos.events.bus import create_event_bus_from_env
from logos.meta.controller import MetaController
from logos.knowledgebase.store import DEFAULT_BASE_PATH
from logos.staging.store import LocalStagingStore

PENDING_INTERACTIONS: Dict[str, Dict[str, Any]] = {}
# PREVIEWS is kept for backwards compatibility with existing callers/tests.
PREVIEWS = PENDING_INTERACTIONS
STAGING_STORE = LocalStagingStore(os.getenv("LOGOS_STAGING_DIR"))
KB_PATH = Path(os.getenv("LOGOS_KB_DIR", str(DEFAULT_BASE_PATH)))


EVENT_BUS = create_event_bus_from_env()


EVENT_BUS_ENABLED = os.getenv("LOGOS_EVENT_BUS_ENABLED", "1").strip() not in {"0", "false", "False"}
_META_CONTROLLER: MetaController | None = None


def get_meta_controller() -> MetaController | None:
    """Return a lazily initialised meta-controller when enabled."""

    global _META_CONTROLLER
    if not EVENT_BUS_ENABLED or not MetaController.is_enabled():
        return None

    if _META_CONTROLLER is None:
        _META_CONTROLLER = MetaController(EVENT_BUS, config_path=KB_PATH / "rules" / "meta_controller.yml")
    return _META_CONTROLLER
