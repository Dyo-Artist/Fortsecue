import asyncio
import httpx
import pytest

from logos import main


@pytest.mark.parametrize(
    "filename,content_type",
    [
        ("test.wav", "audio/wav"),
        ("test.mp3", "audio/mpeg"),
    ],
)
def test_ingest_audio_stores_preview(filename: str, content_type: str) -> None:
    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app), base_url="http://test"
        ) as client:
            files = {"file": (filename, b"0" * 4, content_type)}
            return await client.post("/ingest/audio", files=files)

    response = asyncio.run(_run())
    assert response.status_code == 200
    data = response.json()
    assert data["preview"] == "transcribed"
    assert main.PREVIEW_CACHE[data["interaction_id"]] == "transcribed"
