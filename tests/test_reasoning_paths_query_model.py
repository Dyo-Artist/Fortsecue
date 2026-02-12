from __future__ import annotations

from logos.graphio import queries
from logos.reasoning.path_policy import ReasoningPathPolicy


def test_get_reasoning_paths_uses_supervised_policy(monkeypatch):
    monkeypatch.setattr(queries, "schema_label_groups", lambda: {"risk": ["Risk"]})
    monkeypatch.setattr(queries, "_reasoning_relationship_types", lambda: ["INFLUENCES", "RELATES_TO"])

    def fake_run_query(query: str, params):
        if "RETURN [node IN nodes(p)" in query:
            return [
                {
                    "nodes": [
                        {"id": "s1", "sentiment_score": -0.6, "influence_centrality": 0.9},
                        {"id": "c1", "due_date": "2026-01-01T00:00:00+00:00"},
                    ],
                    "edges": [
                        {"src": "s1", "dst": "c1", "rel": "INFLUENCES", "props": {"at": "2026-01-15T00:00:00+00:00"}},
                        {"src": "c1", "dst": "r1", "rel": "RELATES_TO", "props": {"at": "2026-01-16T00:00:00+00:00"}},
                    ],
                }
            ]
        return []

    monkeypatch.setattr(queries, "run_query", fake_run_query)
    queries._REASONING_POLICY_CACHE = ReasoningPathPolicy(
        id="reasoning_path_scoring",
        version="1.0.0",
        trained_at="2026-01-20T00:00:00+00:00",
        outcomes=("acknowledged", "materialised", "false_positive"),
        intercepts={"materialised": 0.1},
        coefficients={
            "materialised": {
                "path_length": 0.2,
                "recency": 0.3,
                "sentiment_slope": -0.1,
                "commitment_age": 0.01,
                "influence_centrality": 0.6,
                "edge_type::influences": 0.4,
            }
        },
    )

    paths = queries.get_reasoning_paths(stakeholder_id="s1", limit=1, max_hops=3)

    assert len(paths) == 1
    assert "top contributions" in paths[0]["explanation"]
    assert "features" in paths[0]
    assert "contributions" in paths[0]
    assert 0 <= paths[0]["score"] <= 1
