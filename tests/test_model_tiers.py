import pytest
import yaml

import logos.model_tiers as model_tiers
from logos.model_tiers import ModelConfigError


TASK_ID = "extraction_interaction"


def configure_tiers(monkeypatch, tmp_path, tier: str, fallback: str | None = None) -> None:
    config = {"tasks": {TASK_ID: {"tier": tier}}}
    if fallback:
        config["tasks"][TASK_ID]["fallback_tier"] = fallback

    tiers_path = tmp_path / "tiers.yml"
    tiers_path.write_text(yaml.dump(config))
    model_tiers.clear_tier_cache()
    monkeypatch.setattr(model_tiers, "TIERS_PATH", tiers_path)


def configure_model_catalog(
    monkeypatch,
    tmp_path,
    task_models: dict | None = None,
    defaults: dict | None = None,
) -> None:
    data = {
        "defaults": defaults if defaults is not None else {"local_llm": {"name": "default-llm"}},
        "tasks": {TASK_ID: task_models if task_models is not None else {"local_llm": {"name": "task-llm"}}},
    }

    catalog_path = tmp_path / "catalog.yml"
    catalog_path.write_text(yaml.dump(data))
    model_tiers.clear_model_cache()
    monkeypatch.setattr(model_tiers, "MODEL_CONFIG_PATH", catalog_path)


def test_get_model_for_prefers_task_specific(monkeypatch, tmp_path) -> None:
    configure_tiers(monkeypatch, tmp_path, tier="local_llm", fallback="rule_only")
    configure_model_catalog(
        monkeypatch,
        tmp_path,
        task_models={
            "local_llm": {"name": "task-llm", "parameters": {"temperature": 0.0}},
            "rule_only": {"name": "rules-extractor"},
        },
        defaults={"local_llm": {"name": "default-llm"}, "rule_only": {"name": "rules-default"}},
    )

    model = model_tiers.get_model_for(TASK_ID)

    assert model.tier == "local_llm"
    assert model.name == "task-llm"
    assert model.parameters == {"temperature": 0.0}


def test_get_model_for_uses_default_when_task_missing(monkeypatch, tmp_path) -> None:
    configure_tiers(monkeypatch, tmp_path, tier="local_llm", fallback="rule_only")
    configure_model_catalog(
        monkeypatch,
        tmp_path,
        task_models={"rule_only": {"name": "rules-only"}},
        defaults={"local_llm": {"name": "default-llm", "parameters": {"ctx": 2048}}},
    )

    model = model_tiers.get_model_for(TASK_ID)

    assert model.tier == "local_llm"
    assert model.name == "default-llm"
    assert model.parameters == {"ctx": 2048}


def test_get_model_for_falls_back_to_configured_tier(monkeypatch, tmp_path) -> None:
    configure_tiers(monkeypatch, tmp_path, tier="local_llm", fallback="rule_only")
    configure_model_catalog(
        monkeypatch,
        tmp_path,
        task_models={"rule_only": {"name": "rules-only"}},
        defaults={"rule_only": {"name": "rules-default"}},
    )

    model = model_tiers.get_model_for(TASK_ID)

    assert model.tier == "rule_only"
    assert model.name == "rules-only"


def test_get_model_for_raises_when_no_model_defined(monkeypatch, tmp_path) -> None:
    configure_tiers(monkeypatch, tmp_path, tier="local_llm", fallback="rule_only")
    configure_model_catalog(
        monkeypatch,
        tmp_path,
        task_models={},
        defaults={},
    )

    with pytest.raises(ModelConfigError):
        model_tiers.get_model_for(TASK_ID)
