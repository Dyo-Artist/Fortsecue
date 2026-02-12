import logging

from logos.learning.embeddings.concept_assignment import ConceptAssignmentEngine, ConceptAssignmentSettings


def test_assignment_prefers_highest_embedding_similarity():
    engine = ConceptAssignmentEngine(
        ConceptAssignmentSettings(
            embedding_similarity_threshold=0.1,
            decision_threshold=0.1,
            embedding_weight=0.9,
            structural_weight=0.05,
            lexical_weight=0.05,
            ambiguity_gap=0.01,
        )
    )

    result = engine.assign(
        concept_key="stakeholder_types",
        value="foo",
        value_embedding=[1.0, 0.0, 0.0],
        context={"entity_type": "person"},
        candidates=[
            {"id": "st_low", "name": "Low Similarity", "embedding": [0.1, 0.9, 0.0], "applies_to": ["Person"]},
            {"id": "st_best", "name": "Best Similarity", "embedding": [0.99, 0.02, 0.0], "applies_to": ["Person"]},
            {"id": "st_mid", "name": "Mid Similarity", "embedding": [0.7, 0.2, 0.0], "applies_to": ["Person"]},
        ],
    )

    assert result["status"] == "matched"
    assert result["canonical_id"] == "st_best"
    assert result["candidates"][0]["embedding_similarity"] > result["candidates"][1]["embedding_similarity"]


def test_assignment_logs_threshold_and_competing_candidates(caplog):
    engine = ConceptAssignmentEngine(ConceptAssignmentSettings(decision_threshold=0.4, embedding_similarity_threshold=0.3))
    caplog.set_level(logging.INFO)

    engine.assign(
        concept_key="risk_categories",
        value="commercial",
        value_embedding=[1.0, 0.0],
        candidates=[
            {"id": "rc_commercial", "name": "Commercial", "embedding": [0.95, 0.05]},
            {"id": "rc_operational", "name": "Operational", "embedding": [0.5, 0.5]},
        ],
    )

    assert "decision_threshold" in caplog.text
    assert "Competing concept candidates" in caplog.text
