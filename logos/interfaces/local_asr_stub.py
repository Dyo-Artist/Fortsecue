"""Local ASR stub used during development and testing."""

from __future__ import annotations

from typing import Any, Dict


class TranscriptionFailure(RuntimeError):
    """Raised when the stub cannot provide a transcription."""


def transcribe(source_uri: str) -> Dict[str, Any]:
    """Return a deterministic stub transcript for the given URI."""
    if not source_uri:
        raise TranscriptionFailure("Source URI is required for transcription")
    transcript_text = f"Transcribed audio from {source_uri}"
    return {
        "text": transcript_text,
        "duration": 0.0,
        "speaker_segments": [],
    }
