from pathlib import Path

from logos.normalise import bundle


def _write_relationship_types(tmp_path: Path) -> Path:
    rel_types_path = tmp_path / "relationship_types.yml"
    rel_types_path.write_text(
        """
relationship_types:
  WORKS_FOR:
    aliases: ["works for", "works-for"]
    properties: []
  RAISED_IN:
    properties: []
  INFLUENCES:
    properties: []
"""
    )
    return rel_types_path


def test_build_interaction_bundle_normalises_relationship_types(tmp_path, request):
    rel_types_path = _write_relationship_types(tmp_path)
    bundle._refresh_relationship_mappings(rel_types_path)
    request.addfinalizer(bundle._refresh_relationship_mappings)

    preview = {
        "entities": {},
        "relationships": [
            {"src": "p1", "dst": "o1", "rel": "works for"},
            {"src": "iss1", "dst": "i1", "rel": "raised_in"},
        ],
    }

    interaction_bundle = bundle.build_interaction_bundle("i1", preview)

    rel_types = {rel.rel for rel in interaction_bundle.relationships}
    assert rel_types == {"WORKS_FOR", "RAISED_IN"}


def test_reasoning_relationships_follow_schema(tmp_path, request):
    rel_types_path = _write_relationship_types(tmp_path)
    bundle._refresh_relationship_mappings(rel_types_path)
    request.addfinalizer(bundle._refresh_relationship_mappings)

    preview = {
        "entities": {},
        "reasoning": [
            {"source": "p1", "target": "p2", "relation": "influences", "explanation": "test"}
        ],
    }

    interaction_bundle = bundle.build_interaction_bundle("i2", preview)

    reasoning_rels = [rel for rel in interaction_bundle.relationships if rel.src == "p1"]
    assert reasoning_rels
    assert reasoning_rels[0].rel == "INFLUENCES"
