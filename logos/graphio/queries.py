"""Reusable Neo4j query helpers for API routes."""

from __future__ import annotations

from datetime import date, datetime, timezone
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


def _relationship_types_by_keywords(
    rel_types: Iterable[str], keywords: Iterable[str]
) -> list[str]:
    lowered = [(rel_type, rel_type.lower()) for rel_type in rel_types]
    matches = [
        rel_type
        for rel_type, lowered_rel in lowered
        if any(keyword in lowered_rel for keyword in keywords)
    ]
    return matches


def _reasoning_relationship_types() -> list[str]:
    rel_types = list(_schema_store().relationship_types.keys())
    keywords = [
        "mention",
        "made",
        "request",
        "relates",
        "related",
        "influence",
        "raised",
        "identified",
        "result",
        "associate",
        "participated",
        "involved",
        "party",
        "work",
        "assist",
    ]
    return _relationship_types_by_keywords(rel_types, keywords)


def _edge_weight(rel_type: str) -> float:
    lowered = rel_type.lower()
    if "influence" in lowered:
        return 1.6
    if "made" in lowered or "requested" in lowered:
        return 1.4
    if "relates" in lowered or "related" in lowered:
        return 1.25
    if "mention" in lowered:
        return 1.15
    if "identified" in lowered or "raised" in lowered:
        return 1.1
    if "involved" in lowered or "participated" in lowered:
        return 1.0
    if "works_for" in lowered or "party" in lowered or "assist" in lowered:
        return 0.95
    return 0.9


def _extract_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        seconds = float(value)
        if seconds > 1e12:
            seconds = seconds / 1000.0
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _recency_factor(rel_props: Mapping[str, Any]) -> float:
    for key in (
        "at",
        "interaction_at",
        "occurred_at",
        "created_at",
        "timestamp",
        "last_seen_at",
        "updated_at",
    ):
        if key in rel_props:
            timestamp = _extract_timestamp(rel_props.get(key))
            break
    else:
        timestamp = None
    if timestamp is None:
        return 0.5
    now = datetime.now(timezone.utc)
    delta_days = max((now - timestamp).total_seconds() / 86400.0, 0.0)
    return 1.0 / (1.0 + delta_days)


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
        "risk": _labels_by_keywords(labels, ["risk"]),
        "interaction": _labels_by_keywords(labels, ["interaction"]),
        "topic": _labels_by_keywords(labels, ["topic"]),
        "contract": _labels_by_keywords(labels, ["contract"]),
        "alert": _labels_by_keywords(labels, ["alert"]),
    }


def schema_relationship_groups() -> dict[str, list[str]]:
    rel_types = list(_schema_store().relationship_types.keys())
    return {
        "involved_in": _relationship_types_by_keywords(rel_types, ["involved"]),
        "works_for": _relationship_types_by_keywords(rel_types, ["works_for", "worksfor"]),
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


def list_alerts(
    *,
    types: Sequence[str] | None = None,
    statuses: Sequence[str] | None = None,
    project_id: str | None = None,
    stakeholder_id: str | None = None,
    org_id: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    skip = max(page - 1, 0) * page_size
    groups = schema_label_groups()
    alert_labels = groups.get("alert", [])
    if not alert_labels:
        return [], 0
    stakeholder_props = sorted(
        set(_property_candidates("stakeholder") + _property_candidates("person"))
    )
    org_props = _property_candidates("org")
    project_props = _property_candidates("project")
    params = {
        "labels": alert_labels,
        "types": list(types) if types else None,
        "statuses": list(statuses) if statuses else None,
        "project_id": project_id,
        "stakeholder_id": stakeholder_id,
        "org_id": org_id,
        "project_props": project_props,
        "stakeholder_props": stakeholder_props,
        "org_props": org_props,
        "skip": skip,
        "limit": page_size,
    }
    filter_clause = (
        "WHERE any(label IN labels(a) WHERE label IN $labels) "
        "AND ($types IS NULL OR a.type IN $types) "
        "AND ($statuses IS NULL OR a.status IN $statuses) "
        "AND ($project_id IS NULL OR any(prop IN $project_props WHERE a[prop] = $project_id)) "
        "AND ("
        "  $stakeholder_id IS NULL "
        "  OR any(prop IN $stakeholder_props WHERE a[prop] = $stakeholder_id) "
        ") "
        "AND ($org_id IS NULL OR any(prop IN $org_props WHERE a[prop] = $org_id)) "
    )
    count_query = (
        "MATCH (a) "
        f"{filter_clause}"
        "RETURN count(a) AS total"
    )
    count_rows = list(run_query(count_query, params))
    total = int(count_rows[0]["total"]) if count_rows else 0
    items_query = (
        "MATCH (a) "
        f"{filter_clause}"
        "RETURN a{.*} AS alert "
        "ORDER BY coalesce(a.last_updated_at, a.first_detected_at) DESC "
        "SKIP $skip LIMIT $limit"
    )
    rows = list(run_query(items_query, params))
    alerts = [row["alert"] for row in rows]
    return alerts, total


def get_reasoning_paths(
    *,
    stakeholder_id: str | None = None,
    project_id: str | None = None,
    limit: int = 3,
    max_hops: int = 4,
) -> list[dict[str, Any]]:
    if not stakeholder_id and not project_id:
        raise ValueError("Provide stakeholder_id or project_id for reasoning paths.")
    start_id = stakeholder_id or project_id
    target_id = project_id if stakeholder_id and project_id else None
    label_groups = schema_label_groups()
    target_labels: list[str] = []
    if target_id is None:
        target_labels = sorted(
            {
                *label_groups.get("risk", []),
                *label_groups.get("issue", []),
                *label_groups.get("commitment", []),
                *label_groups.get("project", []),
                *label_groups.get("contract", []),
                *label_groups.get("topic", []),
                *label_groups.get("person", []),
                *label_groups.get("org", []),
            }
        )
    rel_types = _reasoning_relationship_types()
    if not rel_types:
        return []
    candidate_limit = max(limit * 5, 10)
    query = (
        "MATCH (start {id: $start_id}) "
        "OPTIONAL MATCH (target {id: $target_id}) "
        "WITH start, target "
        "MATCH p = (start)-[rels*1..$max_hops]-(end) "
        "WHERE all(rel IN rels WHERE type(rel) IN $rel_types) "
        "AND ("
        "  ($target_id IS NULL AND (size($target_labels) = 0 "
        "    OR any(label IN labels(end) WHERE label IN $target_labels))) "
        "  OR ($target_id IS NOT NULL AND end = target)"
        ") "
        "RETURN "
        "[node IN nodes(p) | node{.*, labels: labels(node)}] AS nodes, "
        "[rel IN relationships(p) | "
        "{src: startNode(rel).id, dst: endNode(rel).id, rel: type(rel), props: properties(rel)}"
        "] AS edges "
        "LIMIT $candidate_limit"
    )
    rows = list(
        run_query(
            query,
            {
                "start_id": start_id,
                "target_id": target_id,
                "target_labels": target_labels,
                "rel_types": rel_types,
                "max_hops": max_hops,
                "candidate_limit": candidate_limit,
            },
        )
    )
    scored: list[dict[str, Any]] = []
    for row in rows:
        edges = row.get("edges", []) or []
        score = 0.0
        recency_scores: list[float] = []
        rel_summary: list[str] = []
        for edge in edges:
            rel_type = str(edge.get("rel") or "")
            props = edge.get("props") or {}
            weight = _edge_weight(rel_type)
            recency = _recency_factor(props)
            score += weight * recency
            recency_scores.append(recency)
            if rel_type:
                rel_summary.append(rel_type)
        average_recency = sum(recency_scores) / len(recency_scores) if recency_scores else 0.0
        explanation = (
            f"Path score {score:.2f} from edges [{', '.join(rel_summary)}] "
            f"with average recency {average_recency:.2f}."
        )
        scored.append(
            {
                "nodes": row.get("nodes", []),
                "edges": edges,
                "score": score,
                "explanation": explanation,
            }
        )
    scored.sort(key=lambda item: item.get("score", 0.0), reverse=True)
    return scored[: max(limit, 0)]


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


def _project_related_nodes(
    *,
    project_id: str,
    project_labels: Sequence[str],
    target_labels: Sequence[str],
) -> list[dict[str, Any]]:
    rows = list(
        run_query(
            (
                "MATCH (pr {id: $project_id}) "
                "WHERE (size($project_labels) = 0 OR any(label IN labels(pr) WHERE label IN $project_labels)) "
                "OPTIONAL MATCH (pr)-[rel]-(n) "
                "WHERE (size($target_labels) = 0 OR any(label IN labels(n) WHERE label IN $target_labels)) "
                "RETURN collect(DISTINCT n{.*, labels: labels(n)}) AS nodes"
            ),
            {
                "project_id": project_id,
                "project_labels": list(project_labels),
                "target_labels": list(target_labels),
            },
        )
    )
    if not rows:
        return []
    return rows[0].get("nodes", []) or []


def _project_stakeholders(
    *,
    project_id: str,
    project_labels: Sequence[str],
    stakeholder_labels: Sequence[str],
    org_labels: Sequence[str],
    involved_rel_types: Sequence[str],
    works_for_rel_types: Sequence[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = list(
        run_query(
            (
                "MATCH (pr {id: $project_id}) "
                "WHERE (size($project_labels) = 0 OR any(label IN labels(pr) WHERE label IN $project_labels)) "
                "OPTIONAL MATCH (stakeholder)-[r]-(pr) "
                "WHERE (size($stakeholder_labels) = 0 "
                "OR any(label IN labels(stakeholder) WHERE label IN $stakeholder_labels)) "
                "AND (size($involved_rel_types) = 0 OR type(r) IN $involved_rel_types) "
                "OPTIONAL MATCH (stakeholder)-[wf]-(org) "
                "WHERE (size($org_labels) = 0 OR any(label IN labels(org) WHERE label IN $org_labels)) "
                "AND (size($works_for_rel_types) = 0 OR type(wf) IN $works_for_rel_types) "
                "RETURN collect(DISTINCT {"
                "stakeholder: stakeholder{.*, labels: labels(stakeholder)}, "
                "rel_props: properties(r), "
                "rel_type: type(r)"
                "}) AS stakeholders, "
                "collect(DISTINCT org{.*, labels: labels(org)}) AS orgs"
            ),
            {
                "project_id": project_id,
                "project_labels": list(project_labels),
                "stakeholder_labels": list(stakeholder_labels),
                "org_labels": list(org_labels),
                "involved_rel_types": list(involved_rel_types),
                "works_for_rel_types": list(works_for_rel_types),
            },
        )
    )
    if not rows:
        return [], []
    row = rows[0]
    return row.get("stakeholders", []) or [], row.get("orgs", []) or []


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


def _extract_role(rel_props: Mapping[str, Any]) -> tuple[str | None, bool | None]:
    role_type = rel_props.get("role_type") or rel_props.get("role") or rel_props.get("roleType")
    if "is_primary" in rel_props:
        is_primary = rel_props.get("is_primary")
    elif "primary" in rel_props:
        is_primary = rel_props.get("primary")
    else:
        is_primary = rel_props.get("isPrimary")
    return role_type, is_primary


def build_project_map_view(
    *, project_id: str, include_graph: bool = True
) -> dict[str, Any] | None:
    profile = get_node_profile(project_id)
    if profile is None:
        return None

    labels = profile.get("labels", [])
    props = profile.get("props", {})
    profile_payload = {**props, "labels": labels}

    label_groups = schema_label_groups()
    relationship_groups = schema_relationship_groups()

    project_labels = label_groups.get("project", [])
    person_labels = label_groups.get("person", [])
    org_labels = label_groups.get("org", [])
    commitment_labels = label_groups.get("commitment", [])
    issue_labels = label_groups.get("issue", [])
    risk_labels = label_groups.get("risk", [])

    stakeholder_labels = sorted({*person_labels, *org_labels})
    involved_rel_types = relationship_groups.get("involved_in", [])
    works_for_rel_types = relationship_groups.get("works_for", [])

    stakeholder_rows, orgs = _project_stakeholders(
        project_id=project_id,
        project_labels=project_labels,
        stakeholder_labels=stakeholder_labels,
        org_labels=org_labels,
        involved_rel_types=involved_rel_types,
        works_for_rel_types=works_for_rel_types,
    )

    stakeholders: list[dict[str, Any]] = []
    for entry in stakeholder_rows:
        stakeholder = entry.get("stakeholder") or {}
        rel_props = entry.get("rel_props") or {}
        rel_type = entry.get("rel_type")
        role_type, is_primary = _extract_role(rel_props)
        labels_list = stakeholder.get("labels", [])
        payload: dict[str, Any] = {}
        if any(label in labels_list for label in person_labels):
            payload["person"] = stakeholder
        elif any(label in labels_list for label in org_labels):
            payload["org"] = stakeholder
        else:
            payload["entity"] = stakeholder
        if role_type is not None:
            payload["role_type"] = role_type
        if is_primary is not None:
            payload["is_primary"] = bool(is_primary)
        if rel_type:
            payload["relationship_type"] = rel_type
        stakeholders.append(payload)

    commitments = _project_related_nodes(
        project_id=project_id,
        project_labels=project_labels,
        target_labels=commitment_labels,
    )
    issues = _project_related_nodes(
        project_id=project_id,
        project_labels=project_labels,
        target_labels=issue_labels,
    )
    risks = _project_related_nodes(
        project_id=project_id,
        project_labels=project_labels,
        target_labels=risk_labels,
    )

    open_commitments = [
        commitment
        for commitment in commitments
        if not _commitment_is_closed(commitment.get("status"))
    ]

    response: dict[str, Any] = {
        "project": profile_payload,
        "stakeholders": stakeholders,
        "orgs": orgs,
        "commitments": commitments,
        "issues": issues,
        "risks": risks,
        "project_summary": {
            "project": profile_payload,
            "stakeholders": stakeholders,
            "open_commitments": open_commitments,
            "issues": issues,
        },
    }
    if include_graph:
        response["ego_graph"] = get_ego_graph(project_id)
    return response
