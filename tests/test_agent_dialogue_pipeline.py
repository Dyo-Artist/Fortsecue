from __future__ import annotations

import pytest

from logos.core.pipeline_executor import DEFAULT_PIPELINE_PATH, PipelineContext, PipelineLoader, run_pipeline, STAGE_REGISTRY, PipelineStageError
from logos.llm.prompt import PromptEngineError
from logos.pipelines import agent_dialogue


def test_agent_dialogue_pipeline_risk_flow_references_learned_weights(monkeypatch):
    monkeypatch.setattr(
        agent_dialogue,
        "get_top_paths",
        lambda **_: [
            {
                "score": 0.82,
                "explanation": "Path score 0.82 from logistic policy v2.1.0; top contributions: path_length=+0.4.",
                "contributions": {"path_length": 0.4, "recency": 0.2},
                "nodes": [
                    {"id": "risk-1", "concept_id": "risk.delivery", "concept_kind": "RiskCategory"},
                ],
            }
        ],
    )
    monkeypatch.setattr(agent_dialogue, "search_entities", lambda _: [{"id": "e1"}])

    captured: dict[str, object] = {}

    def fake_run_prompt(prompt_path: str, context: dict[str, object]) -> str:
        captured["prompt_path"] = prompt_path
        captured["context"] = context
        signals = context["learned_weight_signals_json"]
        concepts = context["concept_assignments_json"]
        return (
            "Risk explanation: learned path weights show path_length is dominant; "
            f"signals={signals}; concept_assignments={concepts}"
        )

    monkeypatch.setattr(agent_dialogue.PROMPT_ENGINE, "run_prompt", fake_run_prompt)

    loader = PipelineLoader(STAGE_REGISTRY, path=DEFAULT_PIPELINE_PATH)
    ctx = PipelineContext(request_id="req-1", user_id="tester")
    payload = {"query": "Show me risks", "project_id": "project-1"}

    result = run_pipeline("pipeline.agent_dialogue", payload, ctx, loader=loader)

    assert result["reasoning"][0]["contributions"]["path_length"] == 0.4
    assert "learned path weights" in result["agent_response"]
    assert "path_length" in result["agent_response"]
    assert result["concept_assignments"][0]["concept_id"] == "risk.delivery"
    assert captured["prompt_path"] == "agent/explain_risk.yml"


def test_agent_dialogue_pipeline_summary_prompt(monkeypatch):
    monkeypatch.setattr(agent_dialogue, "search_entities", lambda _: [{"id": "e1", "name": "Issue A"}])
    monkeypatch.setattr(agent_dialogue.PROMPT_ENGINE, "run_prompt", lambda *_: "summary response")

    loader = PipelineLoader(STAGE_REGISTRY, path=DEFAULT_PIPELINE_PATH)
    ctx = PipelineContext(request_id="req-2", user_id="tester")
    payload = {"query": "Summarize open issues"}

    result = run_pipeline("pipeline.agent_dialogue", payload, ctx, loader=loader)

    assert result["agent_response"] == "summary response"


def test_agent_dialogue_pipeline_fails_explicitly_when_local_llm_unavailable(monkeypatch):
    monkeypatch.setattr(agent_dialogue, "search_entities", lambda _: [{"id": "e1", "name": "Issue A"}])

    def fail_prompt(*_args, **_kwargs):
        raise PromptEngineError("Local LLM backend unavailable; prompt execution failed.")

    monkeypatch.setattr(agent_dialogue.PROMPT_ENGINE, "run_prompt", fail_prompt)

    loader = PipelineLoader(STAGE_REGISTRY, path=DEFAULT_PIPELINE_PATH)
    ctx = PipelineContext(request_id="req-3", user_id="tester")

    with pytest.raises(PipelineStageError, match="Local LLM backend unavailable"):
        run_pipeline("pipeline.agent_dialogue", {"query": "Summarize risks"}, ctx, loader=loader)
