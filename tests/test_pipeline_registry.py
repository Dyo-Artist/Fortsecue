from logos.knowledgebase import KnowledgebaseStore
from logos.workflows import (
    PipelineConfigError,
    PipelineNotFound,
    RawInputBundle,
    load_pipeline_config,
    run_pipeline,
)


def test_load_pipeline_config_reads_yaml_registry():
    pipelines = load_pipeline_config()
    assert "ingest_preview" in pipelines
    assert pipelines["ingest_preview"] == [
        "logos.workflows.stages.require_raw_input",
        "logos.workflows.stages.tokenise_text",
        "logos.workflows.stages.apply_extraction",
        "logos.workflows.stages.sync_knowledgebase",
        "logos.workflows.stages.build_preview_payload",
    ]
    assert pipelines["commit_interaction"] == [
        "logos.workflows.stages.require_preview_payload",
        "logos.workflows.stages.capture_preview_memory",
        "logos.workflows.stages.resolve_entities_from_graph",
        "logos.workflows.stages.build_interaction_bundle_stage",
        "logos.workflows.stages.upsert_interaction_bundle_stage",
        "logos.workflows.stages.persist_session_memory",
    ]
    assert pipelines["memory_consolidation"] == [
        "logos.workflows.stages.ensure_memory_manager",
        "logos.workflows.stages.consolidate_memory_stage",
    ]


def test_run_pipeline_executes_stages_in_order(tmp_path):
    updater = KnowledgebaseStore(base_path=tmp_path / "kb", actor="tester")
    context: dict[str, object] = {
        "interaction_id": "test1",
        "interaction_type": "document",
        "knowledge_updater": updater,
    }
    raw_bundle = RawInputBundle(text="Alice meets Bob about project Apollo", source_uri="memo-001")

    result = run_pipeline("ingest_preview", raw_bundle, context)

    assert isinstance(result, dict)
    assert result["interaction"]["id"] == "test1"
    assert result["interaction"]["type"] == "document"
    assert result["interaction"]["summary"]
    assert result["entities"]
    assert context.get("trace") == [
        "require_raw_input",
        "tokenise_text",
        "apply_extraction",
        "sync_knowledgebase",
        "build_preview_payload",
    ]


def test_run_pipeline_raises_for_missing_pipeline():
    raw_bundle = RawInputBundle(text="Unconfigured pipeline")
    try:
        run_pipeline("nonexistent_pipeline", raw_bundle, {})
    except PipelineNotFound:
        return
    assert False, "Expected PipelineNotFound to be raised"


def test_pipeline_config_error_for_missing_registry(tmp_path):
    empty_registry = tmp_path / "pipelines.yml"
    empty_registry.write_text("{}", encoding="utf-8")
    pipelines = load_pipeline_config(empty_registry)
    assert pipelines == {}

    missing_registry = tmp_path / "missing.yml"
    try:
        load_pipeline_config(missing_registry)
    except PipelineConfigError:
        return
    assert False, "Expected PipelineConfigError for missing registry file"
