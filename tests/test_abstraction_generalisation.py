from __future__ import annotations

import math

import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from logos.learning.embeddings.concept_assignment import ConceptAssignmentEngine, ConceptAssignmentSettings


def _cosine(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(a * a for a in left)) or 1.0
    right_norm = math.sqrt(sum(b * b for b in right)) or 1.0
    return numerator / (left_norm * right_norm)


def test_abstraction_generalisation_prefers_cow_over_pig() -> None:
    engine = ConceptAssignmentEngine(
        ConceptAssignmentSettings(
            embedding_similarity_threshold=0.05,
            decision_threshold=0.2,
            ambiguity_gap=0.01,
            embedding_weight=0.9,
            structural_weight=0.05,
            lexical_weight=0.05,
        )
    )

    # Concepts
    cow = {"id": "concept_cow", "name": "Cow", "applies_to": ["Concept"]}
    pig = {"id": "concept_pig", "name": "Pig", "applies_to": ["Concept"]}

    # Embeddings
    cow_embedding = engine._embed_text("cow")
    pig_embedding = engine._embed_text("pig")
    tiny_pink_cow_embedding = engine._embed_text("tiny pink cow")

    similarity_matrix = {
        "tiny_pink_cow->cow": _cosine(tiny_pink_cow_embedding, cow_embedding),
        "tiny_pink_cow->pig": _cosine(tiny_pink_cow_embedding, pig_embedding),
    }

    assert similarity_matrix["tiny_pink_cow->cow"] > similarity_matrix["tiny_pink_cow->pig"], (
        "Expected tiny pink cow to be closer to cow than pig. "
        f"Similarity matrix: {similarity_matrix}"
    )

    assignment = engine.assign(
        concept_key="animal_types",
        value="tiny pink cow",
        value_embedding=tiny_pink_cow_embedding,
        context={"entity_type": "concept"},
        candidates=[
            {**cow, "embedding": cow_embedding},
            {**pig, "embedding": pig_embedding},
        ],
    )

    assert assignment["status"] == "matched", f"Expected matched assignment. Similarity matrix: {similarity_matrix}"
    assert assignment["canonical_id"] == "concept_cow", (
        "Expected INSTANCE_OF relation to resolve to Cow concept. "
        f"Similarity matrix: {similarity_matrix}; candidates: {assignment['candidates']}"
    )
