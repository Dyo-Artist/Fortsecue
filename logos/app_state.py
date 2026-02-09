"""Shared application state for LOGOS routes and pipelines."""
from __future__ import annotations

import os
from typing import Any, Dict

from logos.staging.store import LocalStagingStore

PENDING_INTERACTIONS: Dict[str, Dict[str, Any]] = {}
# PREVIEWS is kept for backwards compatibility with existing callers/tests.
PREVIEWS = PENDING_INTERACTIONS
STAGING_STORE = LocalStagingStore(os.getenv("LOGOS_STAGING_DIR"))

