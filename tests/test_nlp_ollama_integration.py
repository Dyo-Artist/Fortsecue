import json

import pytest

import logos.nlp.extract as extract_mod


def test_extract_all_uses_ollama_when_enabled(monkeypatch):
    monkeypatch.setenv("LOGOS_USE_OLLAMA", "1")

    fake_json = json.dumps(
        {
            "entities": {
                "persons": [],
                "orgs": [],
                "projects": [],
                "contracts": [],
                "topics": [],
                "commitments": [],
            },
            "relationships": [],
            "sentiment": -0.5,
            "summary": "From LLM",
        }
    )

    def fake_call_llm(prompt: str) -> str:  # noqa: ARG001
        return fake_json

    monkeypatch.setattr(extract_mod, "call_llm", fake_call_llm)

    result = extract_mod.extract_all("some text")
    assert result["summary"] == "From LLM"
    assert result["sentiment"] == -0.5


def test_extract_all_handles_noisy_llm_json(monkeypatch):
    monkeypatch.setenv("LOGOS_USE_OLLAMA", "1")

    payload = {
        "entities": {
            "persons": [],
            "orgs": [],
            "projects": [],
            "contracts": [],
            "topics": [],
            "commitments": [],
        },
        "relationships": [],
        "sentiment": 0.25,
        "summary": "From noisy LLM",
    }

    noisy_response = "Here is your JSON:\n" + json.dumps(payload) + "\nThank you!"

    def fake_call_llm(prompt: str) -> str:  # noqa: ARG001
        return noisy_response

    monkeypatch.setattr(extract_mod, "call_llm", fake_call_llm)

    result = extract_mod.extract_all("some text")

    assert result["summary"] == "From noisy LLM"
    assert result["sentiment"] == 0.25


def test_extract_all_falls_back_when_disabled(monkeypatch):
    monkeypatch.delenv("LOGOS_USE_OLLAMA", raising=False)

    def raising_call(prompt: str) -> str:  # noqa: ARG001
        raise AssertionError("call_llm should not be called")

    monkeypatch.setattr(extract_mod, "call_llm", raising_call)

    text = "Alice works at Acme Pty Ltd and will deliver by Friday."
    result = extract_mod.extract_all(text)

    assert "Acme Pty Ltd" in result["entities"]["orgs"]
    assert result["summary"].startswith(text[:10])


@pytest.mark.parametrize("flag", ["0", "false", "", None])
def test_extract_all_respects_disabled_flags(monkeypatch, flag):
    if flag is None:
        monkeypatch.delenv("LOGOS_USE_OLLAMA", raising=False)
    else:
        monkeypatch.setenv("LOGOS_USE_OLLAMA", flag)

    called = False

    def raising_call(prompt: str) -> str:  # noqa: ARG001
        nonlocal called
        called = True
        raise AssertionError("call_llm should not be called when disabled")

    monkeypatch.setattr(extract_mod, "call_llm", raising_call)

    extract_mod.extract_all("Sample text")
    assert called is False


def test_extract_all_falls_back_when_prompt_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("LOGOS_USE_OLLAMA", "1")

    missing_prompt = tmp_path / "absent.yml"
    monkeypatch.setattr(extract_mod, "PROMPT_PATH", missing_prompt)

    def raising_call(prompt: str) -> str:  # noqa: ARG001
        raise AssertionError("call_llm should not be invoked when prompt is missing")

    monkeypatch.setattr(extract_mod, "call_llm", raising_call)

    text = "Alice works at Acme Pty Ltd and will deliver by Friday."
    result = extract_mod.extract_all(text)

    assert "Acme Pty Ltd" in result["entities"]["orgs"]
