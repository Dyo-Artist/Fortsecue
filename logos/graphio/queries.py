"""Reusable Neo4j query helpers for API routes."""

from __future__ import annotations

from math import ceil
from typing import Any, Iterable, Mapping, Sequence

from .neo4j_client import run_query
from .schema_store import SchemaStore


def _normalize_label(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _schema_store() -> SchemaStore:
    return SchemaStore()


def _schema_labels() -> list[str]:
    return list(_schema_store().node_types.keys())


def _labels_by_keywords(labels: Iterable[str], keywords: Iterable[str]) -> list[str]:
    lowered = [(label, label.lower()) for label in labels]
    matches = [
        label
        for label, lowered_label in lowered
        if any(keyword in lowered_label for keyword in keywords)
    ]
    return matches


def _property_candidates(keyword: str) -> list[str]:
    store = _schema_store()
    candidates: set[str] = set()
    for definition in store.node_types.values():
        for prop in definition.properties:
            lowered = prop.lower()
            if keyword in lowered and "id" in lowered:
                candidates.add(prop)
    return sorted(candidates)


def schema_label_groups() -> dict[str, list[str]]:
    labels = _schema_labels()
    return {
        "person": _labels_by_keywords(labels, ["person"]),
        "org": _labels_by_keywords(labels, ["org", "organisation", "organization"]),
        "project": _labels_by_keywords(labels, ["project"]),
        "commitment": _labels_by_keywords(labels, ["commitment"]),
        "issue": _labels_by_keywords(labels, ["issue"]),
        "interaction": _labels_by_keywords(labels, ["interaction"]),
        "topic": _labels_by_keywords(labels, ["topic"]),
        "contract": _labels_by_keywords(labels, ["contract"]),
        "alert": _labels_by_keywords(labels, ["alert"]),
    }


def resolve_schema_labels(requested_types: Iterable[str]) -> list[str]:
    values = [value.strip() for value in requested_types if value and value.strip()]
    if not values:
        return []
    labels = _schema_labels()
    direct_map = {label.lower(): label for label in labels}
    normalized_map = {_normalize_label(label): label for label in labels}
    resolved: list[str] = []
    missing: list[str] = []
    for raw in values:
        key = raw.lower()
        label = direct_map.get(key)
        if label is None:
            label = normalized_map.get(_normalize_label(raw))
        if label is None:
            missing.append(raw)
        else:
            resolved.append(label)
    if missing:
        raise ValueError(f"Unknown types: {', '.join(missing)}")
    return sorted(set(resolved))


def pick_entity_label(labels: Sequence[str], preferred: Sequence[str] | None = None) -> str | None:
    for candidate in preferred or []:
        if candidate in labels:
            return candidate
    return labels[0] if labels else None


def search_fulltext(
    *,
    q: str,
    labels: Sequence[str] | None = None,
    org_id: str | None = None,
    project_id: str | None = None,
    page: int = 1,
    page_size: int = 20,
    index_name: str = "logos_name_idx",
) -> tuple[list[dict[str, Any]], int]:
    skip = max(page - 1, 0) * page_size
    label_filters = list(labels) if labels else None
    groups = schema_label_groups()
    org_labels = groups.get("org", [])
    project_labels = groups.get("project", [])
    org_props = _property_candidates("org")
    project_props = _property_candidates("project")
    params = {
        "q": q,
        "labels": label_filters,
        "org_id": org_id,
        "project_id": project_id,
        "org_labels": org_labels,
        "project_labels": project_labels,
        "org_props": org_props,
        "project_props": project_props,
        "skip": skip,
        "limit": page_size,
        "index_name": index_name,
    }
    filter_clause = (
        "WITH node, score, labels(node) AS labels "
        "WHERE ($labels IS NULL OR any(label IN labels WHERE label IN $labels)) "
        "AND ("
        "  $org_id IS NULL "
        "  OR any(prop IN $org_props WHERE node[prop] = $org_id) "
        "  OR EXISTS { "
        "    MATCH (node)--(org) "
        "    WHERE org.id = $org_id "
        "    AND (size($org_labels) = 0 OR any(label IN labels(org) WHERE label IN $org_labels)) "
        "  } "
        ") "
        "AND ("
        "  $project_id IS NULL "
        "  OR any(prop IN $project_props WHERE node[prop] = $project_id) "
        "  OR EXISTS { "
        "    MATCH (node)--(project) "
        "    WHERE project.id = $project_id "
        "    AND (size($project_labels) = 0 OR any(label IN labels(project) WHERE label IN $project_labels)) "
        "  } "
        ") "
    )
    count_query = (
        "CALL db.index.fulltext.queryNodes($index_name, $q) "
        "YIELD node, score "
        f"{filter_clause}"
        "RETURN count(node) AS total"
    )
    count_rows = list(run_query(count_query, params))
    total = int(count_rows[0]["total"]) if count_rows else 0
    items_query = (
        "CALL db.index.fulltext.queryNodes($index_name, $q) "
        "YIELD node, score "
        f"{filter_clause}"
        "RETURN labels(node) AS labels, node{.*} AS props, score "
        "ORDER BY score DESC SKIP $skip LIMIT $limit"
    )
    items = list(run_query(items_query, params))
    return items, total


def _related_nodes_query(depth: int) -> str:
    return (
        "MATCH (s {id: $id}) "
        f"OPTIONAL MATCH (s)-[*1..{depth}]-(n) "
        "WHERE n.id <> $id "
        "AND (size($labels) = 0 OR any(label IN labels(n) WHERE label IN $labels)) "
        "RETURN collect(DISTINCT n{.*, labels: labels(n)}) AS nodes"
    )


def get_node_profile(entity_id: str) -> Mapping[str, Any] | None:
    rows = list(
        run_query(
            "MATCH (n {id: $id}) RETURN labels(n) AS labels, n{.*} AS props LIMIT 1",
            {"id": entity_id},
        )
    )
    if not rows:
        return None
    return {"labels": rows[0].get("labels", []), "props": rows[0].get("props", {})}


def get_related_nodes(
    *,
    entity_id: str,
    labels: Sequence[str],
    depth: int = 2,
) -> list[dict[str, Any]]:
    rows = list(
        run_query(
            _related_nodes_query(depth),
            {"id": entity_id, "labels": list(labels)},
        )
    )
    if not rows:
        return []
    return rows[0].get("nodes", []) or []


def get_interactions(
    *,
    entity_id: str,
    labels: Sequence[str],
    from_date: str | None,
    to_date: str | None,
) -> list[dict[str, Any]]:
    query = (
        "MATCH (s {id: $id}) "
        "OPTIONAL MATCH (s)-[*1..2]-(i) "
        "WHERE (size($labels) = 0 OR any(label IN labels(i) WHERE label IN $labels)) "
        "AND ($from IS NULL OR i.at >= datetime($from)) "
        "AND ($to IS NULL OR i.at <= datetime($to)) "
        "RETURN collect(DISTINCT i{.*, labels: labels(i)}) AS interactions"
    )
    rows = list(
        run_query(
            query,
            {"id": entity_id, "labels": list(labels), "from": from_date, "to": to_date},
        )
    )
    if not rows:
        return []
    return rows[0].get("interactions", []) or []


def get_alerts(
    *,
    entity_id: str,
    labels: Sequence[str],
) -> list[dict[str, Any]]:
    if not labels:
        return []
    query = (
        "MATCH (a) "
        "WHERE any(label IN labels(a) WHERE label IN $labels) "
        "AND (a.stakeholder_id = $id OR a.org_id = $id OR a.entity_id = $id) "
        "RETURN collect(DISTINCT a{.*}) AS alerts"
    )
    rows = list(run_query(query, {"id": entity_id, "labels": list(labels)}))
    if not rows:
        return []
    return rows[0].get("alerts", []) or []


def get_ego_graph(entity_id: str) -> dict[str, list[dict[str, Any]]]:
    rows = list(
        run_query(
            (
                "MATCH (s {id: $id}) "
                "OPTIONAL MATCH (s)-[r]-(n) "
                "WITH collect(DISTINCT s) + collect(DISTINCT n) AS ns, collect(DISTINCT r) AS rels "
                "RETURN "
                "[node IN ns WHERE node IS NOT NULL | node{.*, labels: labels(node)}] AS nodes, "
                "[rel IN rels WHERE rel IS NOT NULL | "
                "{src: startNode(rel).id, dst: endNode(rel).id, rel: type(rel)}] AS edges"
            ),
            {"id": entity_id},
        )
    )
    row = rows[0] if rows else {"nodes": [], "edges": []}
    return {"nodes": row.get("nodes", []), "edges": row.get("edges", [])}


def _commitment_is_closed(status: Any) -> bool:
    if status is None:
        return False
    normalized = str(status).strip().lower()
    return normalized in {"done", "closed", "cancelled", "resolved"}


def build_stakeholder_view(
    *,
    stakeholder_id: str,
    from_date: str | None = None,
    to_date: str | None = None,
    include_graph: bool = False,
) -> dict[str, Any] | None:
    profile = get_node_profile(stakeholder_id)
    if profile is None:
        return None

    labels = profile.get("labels", [])
    props = profile.get("props", {})
    profile_payload = {**props, "labels": labels}
    groups = schema_label_groups()
    person_labels = groups.get("person", [])
    org_labels = groups.get("org", [])
    project_labels = groups.get("project", [])
    contract_labels = groups.get("contract", [])
    issue_labels = groups.get("issue", [])
    commitment_labels = groups.get("commitment", [])
    interaction_labels = groups.get("interaction", [])
    alert_labels = groups.get("alert", [])

    entity_type: str | None = None
    if any(label in labels for label in person_labels):
        entity_type = "person"
    elif any(label in labels for label in org_labels):
        entity_type = "org"
    else:
        entity_type = labels[0].lower() if labels else "entity"

    stakeholder_payload: dict[str, Any] = {"entity_type": entity_type}
    if entity_type == "person":
        linked_orgs = get_related_nodes(
            entity_id=stakeholder_id, labels=org_labels, depth=1
        )
        stakeholder_payload["person"] = profile_payload
        stakeholder_payload["org"] = linked_orgs[0] if linked_orgs else None
    elif entity_type == "org":
        linked_people = get_related_nodes(
            entity_id=stakeholder_id, labels=person_labels, depth=1
        )
        stakeholder_payload["org"] = profile_payload
        stakeholder_payload["persons"] = linked_people
    else:
        stakeholder_payload["profile"] = profile_payload

    interactions = get_interactions(
        entity_id=stakeholder_id,
        labels=interaction_labels,
        from_date=from_date,
        to_date=to_date,
    )
    sentiment_trend = [
        {
            "at": interaction.get("at"),
            "sentiment_score": interaction.get("sentiment_score", interaction.get("sentiment")),
        }
        for interaction in interactions
        if interaction.get("at") is not None
        and interaction.get("sentiment_score", interaction.get("sentiment")) is not None
    ]

    commitments = get_related_nodes(
        entity_id=stakeholder_id, labels=commitment_labels, depth=2
    )
    open_commitments = [c for c in commitments if not _commitment_is_closed(c.get("status"))]
    closed_commitments = [c for c in commitments if _commitment_is_closed(c.get("status"))]

    projects = get_related_nodes(
        entity_id=stakeholder_id, labels=project_labels, depth=2
    )
    contracts = get_related_nodes(
        entity_id=stakeholder_id, labels=contract_labels, depth=2
    )
    issues = get_related_nodes(entity_id=stakeholder_id, labels=issue_labels, depth=2)
    alerts = get_alerts(entity_id=stakeholder_id, labels=alert_labels)

    response: dict[str, Any] = {
        "stakeholder": stakeholder_payload,
        "interactions": interactions,
        "commitments": commitments,
        "commitments_open": open_commitments,
        "commitments_closed": closed_commitments,
        "projects": projects,
        "contracts": contracts,
        "issues": issues,
        "sentiment_trend": sentiment_trend,
        "alerts": alerts,
    }
    if include_graph:
        response["ego_graph"] = get_ego_graph(stakeholder_id)
    return response
