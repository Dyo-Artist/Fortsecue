"""Search helpers for LOGOS graph exploration.

These helpers encapsulate reusable Cypher queries for the FastAPI layer.
They rely on the shared Neo4j client abstraction so callers can treat
`GraphUnavailable` uniformly across the stack.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .neo4j_client import run_query


def search_entities(q: str) -> List[Dict[str, Any]]:
    """Full-text search across entity names using the configured index."""

    results = run_query(
        (
            "CALL db.index.fulltext.queryNodes('logos_name_idx', $q) "
            "YIELD node, score "
            "RETURN labels(node) AS labels, node{.*} AS props, score "
            "ORDER BY score DESC LIMIT 25"
        ),
        {"q": q},
    )
    return [
        {**record["props"], "labels": record["labels"], "_score": record["score"]}
        for record in results
    ]


def search_interactions(q: str) -> Dict[str, List[Dict[str, Any]]]:
    """Search interactions and return a small graph slice for display."""

    results = run_query(
        (
            "MATCH (i:Interaction) "
            "WHERE toLower(coalesce(i.summary, '')) CONTAINS toLower($q) "
            "   OR toLower(coalesce(i.source_uri, '')) CONTAINS toLower($q) "
            "OPTIONAL MATCH (i)-[m:MENTIONS]->(p:Person) "
            "OPTIONAL MATCH (p)-[w:WORKS_FOR]->(o:Org) "
            "WITH i, m, p, w, o "
            "RETURN "
            "collect(DISTINCT i{.*, labels: labels(i)}) AS interactions, "
            "collect(DISTINCT p{.*, labels: labels(p)}) AS persons, "
            "collect(DISTINCT o{.*, labels: labels(o)}) AS orgs, "
            "[rel IN collect(DISTINCT m) WHERE rel IS NOT NULL | "
            "{src: startNode(rel).id, dst: endNode(rel).id, rel: type(rel)}] AS mention_edges, "
            "[rel IN collect(DISTINCT w) WHERE rel IS NOT NULL | "
            "{src: startNode(rel).id, dst: endNode(rel).id, rel: type(rel)}] AS works_for_edges"
        ),
        {"q": q},
    )

    rows = list(results)
    row = rows[0] if rows else {
        "interactions": [],
        "persons": [],
        "orgs": [],
        "mention_edges": [],
        "works_for_edges": [],
    }

    nodes: List[Dict[str, Any]] = []
    for segment in (row.get("interactions", []), row.get("persons", []), row.get("orgs", [])):
        nodes.extend(segment)

    edges: List[Dict[str, Any]] = []
    edges.extend(row.get("mention_edges", []))
    edges.extend(row.get("works_for_edges", []))

    return {"nodes": nodes, "edges": edges}
