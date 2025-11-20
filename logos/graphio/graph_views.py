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


def project_map(project_id: str) -> Dict[str, List[Dict[str, Any]]]:
    """Return a project-centric graph view including related entities."""

    results = run_query(
        (
            "MATCH (pr:Project {id: $project_id}) "
            "OPTIONAL MATCH (pr)<-[:RELATES_TO]-(c:Commitment) "
            "OPTIONAL MATCH (c)<-[:MADE]-(p:Person)-[w:WORKS_FOR]->(o:Org) "
            "OPTIONAL MATCH (o)-[pt:PARTY_TO]->(ct:Contract) "
            "RETURN "
            "[node IN collect(DISTINCT pr) + "
            "collect(DISTINCT c) + "
            "collect(DISTINCT p) + "
            "collect(DISTINCT o) + "
            "collect(DISTINCT ct) "
            "WHERE node IS NOT NULL | "
            "node{.*, labels: labels(node)}] AS nodes, "
            "[rel IN collect(DISTINCT w) + collect(DISTINCT pt) "
            "WHERE rel IS NOT NULL | "
            "{src: startNode(rel).id, dst: endNode(rel).id, rel: type(rel)}] AS edges"
        ),
        {"project_id": project_id},
    )

    rows = list(results)
    row = rows[0] if rows else {"nodes": [], "edges": []}
    return {
        "nodes": row.get("nodes", []),
        "edges": row.get("edges", []),
    }
