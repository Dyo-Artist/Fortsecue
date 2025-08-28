import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

import asyncio
import httpx

from logos import main


def test_ingest_audio_stores_preview():
    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app), base_url="http://test"
        ) as client:
            files = {"file": ("test.wav", b"0" * 4, "audio/wav")}
            return await client.post("/ingest/audio", files=files)

    response = asyncio.run(_run())
    assert response.status_code == 200
    data = response.json()
    assert data["preview"] == "transcribed"
    assert main.PREVIEW_CACHE[data["interaction_id"]] == "transcribed"
