import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

import asyncio
import httpx
from unittest.mock import Mock, patch

from logos import main


async def _post_audio(payload: dict) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://test"
    ) as client:
        return await client.post("/ingest/audio", json=payload)


def test_ingest_audio_success() -> None:
    async def _run() -> httpx.Response:
        with patch("logos.main.transcribe", new=Mock(return_value={"text": "hello world"})):
            return await _post_audio({"source_uri": "file://audio.wav"})

    response = asyncio.run(_run())
    assert response.status_code == 200
    data = response.json()
    assert data["preview"]["interaction"]["summary"] == "hello world"
    assert main.PENDING_INTERACTIONS[data["interaction_id"]] == data["preview"]


def test_ingest_audio_provider_failure() -> None:
    async def _run() -> httpx.Response:
        with patch(
            "logos.main.transcribe", new=Mock(side_effect=main.TranscriptionFailure("boom"))
        ):
            return await _post_audio({"source_uri": "file://audio.wav"})

    response = asyncio.run(_run())
    assert response.status_code == 400
    assert response.json() == {"detail": "boom"}


def test_ingest_audio_empty_payload() -> None:
    response = asyncio.run(_post_audio({"source_uri": ""}))
    assert response.status_code == 400
    assert response.json() == {"detail": "Source URI is required for transcription"}


def test_ingest_audio_invalid_mime_type() -> None:
    response = asyncio.run(_post_audio({}))
    assert response.status_code == 400
    assert response.json() == {"detail": "Source URI is required for transcription"}
