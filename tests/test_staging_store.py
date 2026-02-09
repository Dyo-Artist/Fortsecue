import asyncio
import pathlib
import sys
from datetime import datetime, timezone

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

import httpx
import pytest

from logos import app_state, main
from logos.models.bundles import InteractionMeta, PreviewBundle
from logos.staging.store import LocalStagingStore


def test_local_staging_store_roundtrip(tmp_path):
    store = LocalStagingStore(tmp_path / "staging")
    meta = InteractionMeta(
        interaction_id="i-store-1",
        interaction_type="note",
        source_uri="file://note",
        source_type="text",
        created_by="tester",
    )

    meta = store.create_interaction(meta)
    raw_path = store.save_raw_text(meta.interaction_id, "hello world")
    assert raw_path.exists()

    preview_bundle = PreviewBundle(
        meta=meta,
        interaction={
            "id": meta.interaction_id,
            "type": meta.interaction_type,
            "at": datetime(2024, 1, 1, tzinfo=timezone.utc).isoformat(),
            "summary": "hello",
        },
        entities={},
        relationships=[],
    )
    store.save_preview(meta.interaction_id, preview_bundle)
    store.set_state(meta.interaction_id, "preview_ready")

    loaded = store.get_preview(meta.interaction_id)
    interaction_data = loaded.interaction.model_dump()
    assert interaction_data.get("id") == meta.interaction_id
    assert interaction_data.get("summary") == "hello"

    state = store.get_state(meta.interaction_id)
    assert state.state == "preview_ready"
    assert state.raw_path == raw_path
    assert state.preview_path and state.preview_path.exists()

    store.set_state(meta.interaction_id, "committed")
    committed_state = store.get_state(meta.interaction_id)
    assert committed_state.state == "committed"


@pytest.mark.asyncio
async def test_preview_and_status_endpoints(monkeypatch, tmp_path):
    app_state.STAGING_STORE = LocalStagingStore(tmp_path / "staging")

    meta = InteractionMeta(
        interaction_id="i-endpoint-1",
        interaction_type="document",
        source_uri="file://doc",
        source_type="doc",
        created_by="api",
    )
    app_state.STAGING_STORE.create_interaction(meta)
    preview = PreviewBundle(
        meta=meta,
        interaction={"id": meta.interaction_id, "type": meta.interaction_type, "summary": "summary"},
        entities={},
        relationships=[],
    )
    app_state.STAGING_STORE.save_preview(meta.interaction_id, preview)
    app_state.STAGING_STORE.set_state(meta.interaction_id, "preview_ready")

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
        preview_resp = await client.get(f"/api/v1/interactions/{meta.interaction_id}/preview")
        status_resp = await client.get(f"/api/v1/interactions/{meta.interaction_id}/status")
        missing_resp = await client.get("/api/v1/interactions/unknown/preview")

    assert preview_resp.status_code == 200
    assert preview_resp.json()["interaction"]["id"] == meta.interaction_id
    assert status_resp.status_code == 200
    assert status_resp.json()["state"] == "preview_ready"
    assert missing_resp.status_code == 404
