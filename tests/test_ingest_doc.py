import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

import asyncio
import httpx

from logos import main


def test_ingest_doc_extracts_entities() -> None:
    text = "Jane Smith will send the report to Acme Pty Ltd by 2023-09-30."

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app), base_url="http://test"
        ) as client:
            return await client.post(
                "/ingest/doc", json={"source_uri": "file://example", "text": text}
            )

    response = asyncio.run(_run())
    assert response.status_code == 200
    data = response.json()
    assert data["preview_ready"] is True
    preview = data["preview"]
    assert data["interaction_id"]
    assert preview["interaction"]["type"] == "document"
    assert len(preview["entities"]["orgs"]) >= 1
    assert len(preview["entities"]["persons"]) >= 1
    assert len(preview["entities"]["commitments"]) >= 1
    assert main.PENDING_INTERACTIONS[data["interaction_id"]] == preview
