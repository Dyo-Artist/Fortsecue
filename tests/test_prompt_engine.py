from __future__ import annotations

from pathlib import Path

import pytest

from logos.interfaces.ollama_client import OllamaError
from logos.llm.prompt import PromptEngine, PromptEngineError


def test_prompt_engine_run_prompt_returns_llm_response(monkeypatch, tmp_path: Path):
    prompt_file = tmp_path / "demo.yml"
    prompt_file.write_text("prompt_template: 'Question: {{ query }}'\n")

    engine = PromptEngine(prompts_root=tmp_path)

    monkeypatch.setattr("logos.llm.prompt.call_llm", lambda prompt: f"LLM::{prompt}")

    response = engine.run_prompt("demo.yml", {"query": "What changed?"})

    assert response == "LLM::Question: What changed?"


def test_prompt_engine_run_prompt_fails_explicitly_when_llm_unavailable(monkeypatch, tmp_path: Path):
    prompt_file = tmp_path / "demo.yml"
    prompt_file.write_text("prompt_template: 'Question: {{ query }}'\n")

    engine = PromptEngine(prompts_root=tmp_path)

    def fail_call(_prompt: str) -> str:
        raise OllamaError("connection refused")

    monkeypatch.setattr("logos.llm.prompt.call_llm", fail_call)

    with pytest.raises(PromptEngineError, match="Local LLM backend unavailable"):
        engine.run_prompt("demo.yml", {"query": "Why?"})
