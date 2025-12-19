from importlib.util import find_spec
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
LOGOS_ROOT = REPO_ROOT / "logos"


def test_no_legacy_hcg_package_present() -> None:
    """Ensure the legacy logos_hcg client is not part of the codebase."""

    legacy_dirs = list(LOGOS_ROOT.rglob("logos_hcg"))
    assert not legacy_dirs, f"Found unexpected legacy logos_hcg paths: {legacy_dirs}"
    assert find_spec("logos_hcg") is None


def test_single_graphio_upsert_and_schema_store() -> None:
    """Only the canonical GraphIO implementations should exist."""

    upsert_files = list(LOGOS_ROOT.rglob("upsert.py"))
    schema_store_files = list(LOGOS_ROOT.rglob("schema_store.py"))

    assert upsert_files == [LOGOS_ROOT / "graphio" / "upsert.py"]
    assert schema_store_files == [LOGOS_ROOT / "graphio" / "schema_store.py"]
