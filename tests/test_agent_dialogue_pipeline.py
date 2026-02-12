from __future__ import annotations

from logos.core.pipeline_executor import DEFAULT_PIPELINE_PATH, PipelineContext, PipelineLoader, run_pipeline, STAGE_REGISTRY
from logos.pipelines import agent_dialogue


def test_agent_dialogue_pipeline_risk_flow(monkeypatch):
    monkeypatch.setattr(agent_dialogue, "get_top_paths", lambda **_: [{"path": "p1"}])
    monkeypatch.setattr(agent_dialogue, "search_entities", lambda _: [{"id": "e1"}])

    loader = PipelineLoader(STAGE_REGISTRY, path=DEFAULT_PIPELINE_PATH)
    ctx = PipelineContext(request_id="req-1", user_id="tester")
    payload = {"query": "Show me risks", "project_id": "project-1"}

    result = run_pipeline("pipeline.agent_dialogue", payload, ctx, loader=loader)

    assert "Explain the risk context" in result["agent_response"]
    assert "User query: Show me risks" in result["agent_response"]
    assert result["reasoning"] == [{"path": "p1"}]
    assert "feedback_bundle" in result


def test_agent_dialogue_pipeline_summary_prompt(monkeypatch):
    monkeypatch.setattr(agent_dialogue, "search_entities", lambda _: [{"id": "e1", "name": "Issue A"}])

    loader = PipelineLoader(STAGE_REGISTRY, path=DEFAULT_PIPELINE_PATH)
    ctx = PipelineContext(request_id="req-2", user_id="tester")
    payload = {"query": "Summarize open issues"}

    result = run_pipeline("pipeline.agent_dialogue", payload, ctx, loader=loader)

    assert "Summarise the current risk and issue posture" in result["agent_response"]
    assert "User query: Summarize open issues" in result["agent_response"]
