import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

import asyncio
import httpx
from unittest.mock import AsyncMock, patch

from logos import main
from logos.services.transcription import TranscriptionError


async def _post_audio(filename: str, mimetype: str, data: bytes) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://test"
    ) as client:
        files = {"file": (filename, data, mimetype)}
        return await client.post("/ingest/audio", files=files)


def test_ingest_audio_success() -> None:
    async def _run() -> httpx.Response:
        with patch("logos.main.transcribe_audio", new=AsyncMock(return_value="hello world")):
            return await _post_audio("test.wav", "audio/wav", b"0" * 4)

    response = asyncio.run(_run())
    assert response.status_code == 200
    data = response.json()
    assert data["preview"]["interaction"]["summary"] == "hello world"
    assert main.PREVIEWS[data["interaction_id"]] == data["preview"]


def test_ingest_audio_provider_failure() -> None:
    async def _run() -> httpx.Response:
        with patch(
            "logos.main.transcribe_audio",
            new=AsyncMock(side_effect=TranscriptionError("boom")),
        ):
            return await _post_audio("test.wav", "audio/wav", b"0" * 4)

    response = asyncio.run(_run())
    assert response.status_code == 502
    assert response.json() == {"detail": "Transcription failed"}


def test_ingest_audio_empty_payload() -> None:
    response = asyncio.run(_post_audio("test.wav", "audio/wav", b""))
    assert response.status_code == 400
    assert response.json() == {"detail": "Empty file"}


def test_ingest_audio_invalid_mime_type() -> None:
    response = asyncio.run(_post_audio("test.txt", "text/plain", b"data"))
    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid audio type"}
