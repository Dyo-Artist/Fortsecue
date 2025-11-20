"""Graph view helpers used by the UI layer."""

from __future__ import annotations

from typing import Any, Dict, List

from .neo4j_client import run_query


def ego_network(person_id: str) -> Dict[str, List[Dict[str, Any]]]:
    """Return an ego network centred on a person."""

    results = run_query(
        (
            "MATCH (p:Person {id: $person_id}) "
            "OPTIONAL MATCH (p)-[r]-(n) "
            "WITH collect(DISTINCT p) + collect(DISTINCT n) AS ns, collect(DISTINCT r) AS rels "
            "RETURN "
            "[node IN ns WHERE node IS NOT NULL | node{.*, labels: labels(node)}] AS nodes, "
            "[rel IN rels WHERE rel IS NOT NULL | {src: startNode(rel).id, dst: endNode(rel).id, rel: type(rel)}] AS edges"
        ),
        {"person_id": person_id},
    )

    rows = list(results)
    row = rows[0] if rows else {"nodes": [], "edges": []}
    return {
        "nodes": row.get("nodes", []),
        "edges": row.get("edges", []),
    }
