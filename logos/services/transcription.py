"""Audio transcription service integration."""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx


class TranscriptionError(RuntimeError):
    """Raised when the transcription provider fails."""


_OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
_OPENAI_MODEL_ENV = "OPENAI_WHISPER_MODEL"
_DEFAULT_MODEL = "whisper-1"
_TRANSCRIBE_URL = "https://api.openai.com/v1/audio/transcriptions"


@dataclass(slots=True)
class _OpenAIConfig:
    api_key: str
    model: str


def _load_openai_config() -> _OpenAIConfig:
    try:
        api_key = os.environ[_OPENAI_API_KEY_ENV]
    except KeyError as exc:  # pragma: no cover - defensive guard
        raise TranscriptionError("OpenAI API key is not configured") from exc
    model = os.environ.get(_OPENAI_MODEL_ENV, _DEFAULT_MODEL)
    return _OpenAIConfig(api_key=api_key, model=model)


async def transcribe_audio(content: bytes, mime_type: str) -> str:
    """Transcribe the given audio bytes using the OpenAI Whisper API."""

    if not content:
        raise TranscriptionError("Cannot transcribe empty content")

    config = _load_openai_config()
    filename = f"upload.{mime_type.split('/')[-1] if '/' in mime_type else 'wav'}"

    headers = {"Authorization": f"Bearer {config.api_key}"}
    data = {"model": config.model}
    files = {"file": (filename, content, mime_type)}

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            response = await client.post(
                _TRANSCRIBE_URL,
                headers=headers,
                data=data,
                files=files,
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:  # pragma: no cover - passthrough
        raise TranscriptionError("Transcription provider request failed") from exc

    try:
        payload = response.json()
    except ValueError as exc:  # pragma: no cover - invalid JSON
        raise TranscriptionError("Invalid transcription response") from exc

    text = payload.get("text")
    if not isinstance(text, str):  # pragma: no cover - defensive guard
        raise TranscriptionError("Transcription response missing text")

    return text

