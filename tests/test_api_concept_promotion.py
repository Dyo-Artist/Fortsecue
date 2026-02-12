import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from logos import main
from logos.api.routes import concepts as concept_routes
from logos.learning.clustering.concept_governance import ConceptPromotionError, PromotionResult


def test_promote_concept_endpoint_success(monkeypatch):
    client = TestClient(main.app)

    def fake_promote(concept_id: str, *, promoted_by: str = "api"):
        assert concept_id == "c-1"
        assert promoted_by == "reviewer-1"
        return PromotionResult(
            concept_id=concept_id,
            status="canonical",
            converted_relationships=4,
            provenance={"source": "test"},
        )

    monkeypatch.setattr(concept_routes, "promote_concept", fake_promote)

    response = client.post("/concept/promote/c-1", headers={"x-actor-id": "reviewer-1"})

    assert response.status_code == 200
    assert response.json() == {
        "concept_id": "c-1",
        "status": "canonical",
        "converted_relationships": 4,
        "promotion_provenance": {"source": "test"},
    }


def test_promote_concept_endpoint_rejects_non_proposed(monkeypatch):
    client = TestClient(main.app)

    def fake_promote(concept_id: str, *, promoted_by: str = "api"):
        raise ConceptPromotionError(
            code="CONCEPT_NOT_PROPOSED",
            message="Only proposed concepts can be promoted",
            concept_id=concept_id,
        )

    monkeypatch.setattr(concept_routes, "promote_concept", fake_promote)
    response = client.post("/api/v1/concept/promote/c-2")

    assert response.status_code == 409
    assert response.json()["error"] == "concept_not_proposed"
