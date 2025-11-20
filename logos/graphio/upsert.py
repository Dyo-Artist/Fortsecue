from typing import Optional, Sequence

from .neo4j_client import run_query


def upsert_org(org_id: str, name: str) -> None:
    """Upsert an Org node."""
    run_query(
        "MERGE (o:Org {id: $id}) SET o.name = $name",
        {"id": org_id, "name": name},
    )


def upsert_person(person_id: str, name: str, org_id: Optional[str] = None) -> None:
    """Upsert a Person node and optionally relate it to an Org."""
    query = "MERGE (p:Person {id: $id}) SET p.name = $name"
    params = {"id": person_id, "name": name}
    if org_id:
        query += " MERGE (o:Org {id: $org_id}) MERGE (p)-[:WORKS_FOR]->(o)"
        params["org_id"] = org_id
    run_query(query, params)


def upsert_project(project_id: str, name: str, status: Optional[str] = None) -> None:
    """Upsert a Project node."""
    query = "MERGE (p:Project {id: $id}) SET p.name = $name, p.last_seen = datetime()"
    params = {"id": project_id, "name": name}
    if status:
        query += ", p.status = $status"
        params["status"] = status
    run_query(query, params)


def upsert_contract(
    contract_id: str,
    name: Optional[str] = None,
    sap_id: Optional[str] = None,
    value: Optional[float] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> None:
    """Upsert a Contract node with optional metadata."""

    params: dict[str, object] = {"id": contract_id}
    set_parts = ["c.last_seen = datetime()"]

    if name:
        params["name"] = name
        set_parts.append("c.name = $name")
    if sap_id:
        params["sap_id"] = sap_id
        set_parts.append("c.sap_id = $sap_id")
    if value is not None:
        params["value"] = value
        set_parts.append("c.value = $value")
    if start_date:
        params["start_date"] = start_date
        set_parts.append("c.start_date = date($start_date)")
    if end_date:
        params["end_date"] = end_date
        set_parts.append("c.end_date = date($end_date)")

    query = "MERGE (c:Contract {id: $id}) SET " + ", ".join(set_parts)
    run_query(query, params)


def upsert_topic(topic_id: str, name: str) -> None:
    """Upsert a Topic node."""
    run_query(
        "MERGE (t:Topic {id: $id}) SET t.name = $name, t.last_seen = datetime()",
        {"id": topic_id, "name": name},
    )


def upsert_interaction(
    interaction_id: str,
    type_: str,
    at: str,
    sentiment: float,
    summary: str,
    source_uri: str,
    mention_person_ids: Optional[Sequence[str]] = None,
) -> None:
    """Upsert an Interaction node and optional MENTIONS relations."""
    query = (
        "MERGE (i:Interaction {id: $id}) "
        "SET i.type=$type, i.at=datetime($at), i.sentiment=$sentiment, "
        "i.summary=$summary, i.source_uri=$source_uri, i.last_seen=datetime()"
    )
    params = {
        "id": interaction_id,
        "type": type_,
        "at": at,
        "sentiment": sentiment,
        "summary": summary,
        "source_uri": source_uri,
    }
    if mention_person_ids:
        query += (
            " WITH i UNWIND $mention_ids AS mid MERGE (p:Person {id: mid}) "
            "MERGE (i)-[:MENTIONS]->(p)"
        )
        params["mention_ids"] = list(mention_person_ids)
    run_query(query, params)


def upsert_commitment(
    commitment_id: str,
    text: str,
    person_id: str,
    *,
    due_date: Optional[str] = None,
    status: str = "open",
    relates_to_project_id: Optional[str] = None,
    relates_to_contract_id: Optional[str] = None,
) -> None:
    """Upsert a Commitment node with provenance and relationships.

    All LOGOS nodes must carry last_seen for provenance. Commitments also
    optionally relate to a Project or Contract via RELATES_TO.
    """

    params: dict[str, object] = {
        "id": commitment_id,
        "text": text,
        "status": status,
        "person_id": person_id,
    }

    set_parts = ["c.text = $text", "c.status = $status", "c.last_seen = datetime()"]
    if due_date:
        params["due_date"] = due_date
        set_parts.append("c.due_date = date($due_date)")

    query_parts = [
        "MERGE (c:Commitment {id: $id})",
        "SET " + ", ".join(set_parts),
        "MERGE (p:Person {id: $person_id})",
        "MERGE (p)-[:MADE]->(c)",
    ]

    if relates_to_project_id:
        params["project_id"] = relates_to_project_id
        query_parts.append("MERGE (pr:Project {id: $project_id})")
        query_parts.append("MERGE (c)-[:RELATES_TO]->(pr)")
    if relates_to_contract_id:
        params["contract_id"] = relates_to_contract_id
        query_parts.append("MERGE (ct:Contract {id: $contract_id})")
        query_parts.append("MERGE (c)-[:RELATES_TO]->(ct)")

    run_query(" ".join(query_parts), params)


def upsert_relationship(
    src_id: str,
    dst_id: str,
    rel_type: str,
    *,
    src_label: Optional[str] = None,
    dst_label: Optional[str] = None,
    properties: Optional[dict[str, object]] = None,
) -> None:
    """Create or update a relationship between two existing nodes."""

    allowed = {"MADE", "RELATES_TO", "WORKS_FOR", "INVOLVED_IN", "PARTY_TO", "MENTIONS", "INFLUENCES"}
    if rel_type not in allowed:
        raise ValueError(f"Unsupported relationship type: {rel_type}")

    src = "(a" + (f":{src_label}" if src_label else "") + " {id: $src})"
    dst = "(b" + (f":{dst_label}" if dst_label else "") + " {id: $dst})"
    query = f"MATCH {src} MATCH {dst} MERGE (a)-[r:{rel_type}]->(b)"
    params: dict[str, object] = {"src": src_id, "dst": dst_id}
    if properties:
        query += " SET r += $props"
        params["props"] = properties
    run_query(query, params)
