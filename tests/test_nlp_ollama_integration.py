import json

import pytest
import yaml

import logos.model_tiers as model_tiers
import logos.nlp.extract as extract_mod


@pytest.fixture
def configure_extraction_tier(monkeypatch, tmp_path):
    def _configure(tier: str, fallback: str | None = None) -> None:
        path = tmp_path / "tiers.yml"
        config = {
            "tasks": {
                extract_mod.EXTRACTION_TASK_ID: {
                    "tier": tier,
                }
            }
        }
        if fallback:
            config["tasks"][extract_mod.EXTRACTION_TASK_ID]["fallback_tier"] = fallback

        path.write_text(yaml.safe_dump(config), encoding="utf-8")
        model_tiers.clear_tier_cache()
        monkeypatch.setattr(model_tiers, "TIERS_PATH", path)

    return _configure


def test_extract_all_uses_llm_when_configured(monkeypatch, configure_extraction_tier):
    configure_extraction_tier(tier="local_llm", fallback="rule_only")

    fake_json = json.dumps(
        {
            "interaction_proposal": {
                "summary": "From LLM",
                "sentiment_score": -0.5,
                "type": "note",
            },
            "entities": {
                "persons": [],
                "orgs": [],
            },
        }
    )

    def fake_call_llm(prompt: str) -> str:  # noqa: ARG001
        return fake_json

    monkeypatch.setattr(extract_mod, "call_llm", fake_call_llm)

    result = extract_mod.extract_all("some text")
    assert result["summary"] == "From LLM"
    assert result["sentiment"] == -0.5
    assert result["entities"]["issues"] == []
    assert result["entities"]["risks"] == []


def test_extract_all_handles_noisy_llm_json(monkeypatch, configure_extraction_tier):
    configure_extraction_tier(tier="local_llm", fallback="rule_only")

    payload = {
        "interaction_proposal": {
            "summary": "From noisy LLM",
            "sentiment_score": 0.25,
        },
        "entities": {
            "persons": [],
        },
    }

    noisy_response = "Here is your JSON:\n" + json.dumps(payload) + "\nThank you!"

    def fake_call_llm(prompt: str) -> str:  # noqa: ARG001
        return noisy_response

    monkeypatch.setattr(extract_mod, "call_llm", fake_call_llm)

    result = extract_mod.extract_all("some text")

    assert result["summary"] == "From noisy LLM"
    assert result["sentiment"] == 0.25
    assert result["entities"]["issues"] == []
    assert result["entities"]["risks"] == []


def test_extract_all_falls_back_when_rule_only(monkeypatch, configure_extraction_tier):
    configure_extraction_tier(tier="rule_only")

    def raising_call(prompt: str) -> str:  # noqa: ARG001
        raise AssertionError("call_llm should not be called")

    monkeypatch.setattr(extract_mod, "call_llm", raising_call)

    text = "Alice works at Acme Pty Ltd and will deliver by Friday."
    result = extract_mod.extract_all(text)

    assert "Acme Pty Ltd" in result["entities"]["orgs"]
    assert result["summary"].startswith(text[:10])
    assert result["entities"]["issues"] == []
    assert result["entities"]["risks"] == []


def test_extract_all_falls_back_when_llm_errors(monkeypatch, configure_extraction_tier):
    configure_extraction_tier(tier="local_llm", fallback="rule_only")

    called = False

    def raising_call(prompt: str) -> str:  # noqa: ARG001
        nonlocal called
        called = True
        raise extract_mod.OllamaError("Unavailable")

    monkeypatch.setattr(extract_mod, "call_llm", raising_call)

    extract_mod.extract_all("Sample text")
    assert called is True


def test_extract_all_falls_back_when_prompt_missing(monkeypatch, tmp_path, configure_extraction_tier):
    configure_extraction_tier(tier="local_llm", fallback="rule_only")

    missing_prompt = tmp_path / "absent.yml"
    monkeypatch.setattr(extract_mod, "PROMPT_PATH", missing_prompt)

    def raising_call(prompt: str) -> str:  # noqa: ARG001
        raise AssertionError("call_llm should not be invoked when prompt is missing")

    monkeypatch.setattr(extract_mod, "call_llm", raising_call)

    text = "Alice works at Acme Pty Ltd and will deliver by Friday."
    result = extract_mod.extract_all(text)

    assert "Acme Pty Ltd" in result["entities"]["orgs"]


def test_commitment_patterns_loaded_from_lexicon(monkeypatch, tmp_path, configure_extraction_tier):
    configure_extraction_tier(tier="rule_only")
    lexicon = tmp_path / "obligation_phrases.yml"
    lexicon.write_text(
        """patterns:
  - regex: '\\bobligated to\\b[^.]+'
    flags:
      - IGNORECASE
""",
        encoding="utf-8",
    )

    original_path = extract_mod.OBLIGATION_LEXICON_PATH
    monkeypatch.setattr(extract_mod, "OBLIGATION_LEXICON_PATH", lexicon)

    extract_mod._refresh_obligation_patterns()

    text = "Contoso is obligated to deliver the new components by Monday."
    result = extract_mod.extract_all(text)

    assert "obligated to deliver the new components by Monday" in result["entities"]["commitments"]

    extract_mod._refresh_obligation_patterns(original_path)
