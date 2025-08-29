import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

import asyncio
import httpx
import pytest

from logos import main


@pytest.mark.parametrize(
    ("filename", "mimetype"),
    [("test.wav", "audio/wav"), ("test.mp3", "audio/mpeg")],
)
def test_ingest_audio_stores_preview(filename: str, mimetype: str) -> None:
    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app), base_url="http://test"
        ) as client:
            files = {"file": (filename, b"0" * 4, mimetype)}
            return await client.post("/ingest/audio", files=files)

    response = asyncio.run(_run())
    assert response.status_code == 200
    data = response.json()
    assert data["preview"]["interaction"]["summary"] == "transcribed"
    assert main.PREVIEWS[data["interaction_id"]] == data["preview"]
