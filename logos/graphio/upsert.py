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


def upsert_commitment(commitment_id: str, description: str, person_id: str) -> None:
    """Upsert a Commitment node and relate it to a Person via MADE."""
    run_query(
        "MERGE (c:Commitment {id: $id}) SET c.description = $description MERGE (p:Person {id: $person_id}) MERGE (p)-[:MADE]->(c)",
        {"id": commitment_id, "description": description, "person_id": person_id},
    )
