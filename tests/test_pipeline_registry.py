from logos.workflows import (
    ExtractionBundle,
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
        "logos.workflows.stages.build_preview_bundle",
    ]


def test_run_pipeline_executes_stages_in_order():
    context: dict[str, object] = {}
    raw_bundle = RawInputBundle(text="Alice meets Bob about project Apollo", source_uri="memo-001")

    result = run_pipeline("ingest_preview", raw_bundle, context)

    assert isinstance(result, ExtractionBundle)
    assert result.text == raw_bundle.text
    assert result.tokens[:2] == ["Alice", "meets"]
    assert context.get("trace") == [
        "require_raw_input",
        "tokenise_text",
        "build_preview_bundle",
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

