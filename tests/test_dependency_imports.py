import importlib


def test_runtime_dependencies_importable():
    modules = [
        "fastapi",
        "pydantic",
        "yaml",
        "httpx",
        "uvicorn",
        "neo4j",
    ]

    loaded = [importlib.import_module(module) for module in modules]
    assert all(module is not None for module in loaded)
