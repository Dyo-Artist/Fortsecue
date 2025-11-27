"""Client for interacting with a local Ollama LLM instance."""

from __future__ import annotations

import json
import os
from typing import Final

import httpx

DEFAULT_OLLAMA_URL: Final = "http://localhost:11434/api/generate"
DEFAULT_MODEL_NAME: Final = "gpt-oss:20b"


class OllamaError(RuntimeError):
    """Raised when Ollama returns an error or unexpected payload."""


def _get_env(name: str, default: str) -> str:
    value = os.getenv(name, default)
    return value if value else default


def call_llm(prompt: str) -> str:
    """
    Call local gpt-oss via Ollama and return the generated text.

    Raises
    ------
    OllamaError
        If an HTTP error occurs or the response cannot be parsed.
    """

    url = _get_env("OLLAMA_URL", DEFAULT_OLLAMA_URL)
    model_name = _get_env("OLLAMA_MODEL", DEFAULT_MODEL_NAME)

    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.0,
            "top_p": 1.0,
            "num_predict": 512,
        },
    }

    try:
        response = httpx.post(url, json=payload, timeout=600)
    except httpx.HTTPError as exc:  # pragma: no cover - network failure handling
        raise OllamaError(f"Failed to contact Ollama: {exc}") from exc

    if response.status_code != 200:
        raise OllamaError(
            f"Ollama returned status {response.status_code}: {response.text}"
        )

    try:
        data = response.json()
    except json.JSONDecodeError as exc:
        raise OllamaError("Failed to parse Ollama response as JSON") from exc

    generated = data.get("response")
    if not isinstance(generated, str):
        raise OllamaError("Ollama response missing 'response' field")

    return generated
