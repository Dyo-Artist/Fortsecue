from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Iterable, Sequence

from pydantic import BaseModel, ConfigDict, Field


class ConceptModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    kind: str
    name: str | None = None
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    source_uri: str | None = None


class OrgModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str | None = None
    domain: str | None = None
    sector: str | None = None
    source_uri: str | None = None


class PersonModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str | None = None
    title: str | None = None
    email: str | None = None
    org_id: str | None = None
    influence_score: float | None = None
    source_uri: str | None = None


class ProjectModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str | None = None
    status: str | None = None
    source_uri: str | None = None


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str | None = None
    sap_id: str | None = None
    value: float | None = None
    start_date: date | None = None
    end_date: date | None = None
    org_ids: list[str] = Field(default_factory=list)
    source_uri: str | None = None


class TopicModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str | None = None
    source_uri: str | None = None


class CommitmentModel(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str
    text: str
    owner_id: str = Field(alias="person_id")
    due_date: date | None = None
    status: str = "open"
    relates_to_project_id: str | None = None
    relates_to_contract_id: str | None = None
    source_uri: str | None = None


class InteractionModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    type: str
    at: datetime | None = None
    sentiment: float | None = None
    summary: str | None = None
    source_uri: str | None = None


class RelationshipModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    src: str
    dst: str
    rel: str
    src_label: str | None = None
    dst_label: str | None = None
    properties: dict[str, Any] | None = None
    source_uri: str | None = None


class EntitiesModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    stakeholder_types: list[ConceptModel] = Field(default_factory=list)
    risk_categories: list[ConceptModel] = Field(default_factory=list)
    topic_groups: list[ConceptModel] = Field(default_factory=list)
    orgs: list[OrgModel] = Field(default_factory=list)
    persons: list[PersonModel] = Field(default_factory=list)
    projects: list[ProjectModel] = Field(default_factory=list)
    contracts: list[ContractModel] = Field(default_factory=list)
    topics: list[TopicModel] = Field(default_factory=list)
    commitments: list[CommitmentModel] = Field(default_factory=list)


class InteractionBundle(BaseModel):
    model_config = ConfigDict(extra="ignore")

    interaction: InteractionModel
    entities: EntitiesModel
    relationships: list[RelationshipModel] = Field(default_factory=list)


_ALLOWED_RELATIONSHIPS = {
    "MADE",
    "RELATES_TO",
    "WORKS_FOR",
    "INVOLVED_IN",
    "PARTY_TO",
    "MENTIONS",
    "INFLUENCES",
}


def _dt_param(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def upsert_concept(tx, concept: ConceptModel, now: datetime) -> None:
    cypher = (
        "MERGE (c:Concept {id: $id}) "
        "SET c.name = $name, c.kind = $kind, c.description = $description, "
        "c.metadata = $metadata, c.source_uri = $source_uri, c.last_seen = datetime($now)"
    )
    tx.run(
        cypher,
        {
            "id": concept.id,
            "name": concept.name or concept.id,
            "kind": concept.kind,
            "description": concept.description,
            "metadata": concept.metadata or {},
            "source_uri": concept.source_uri,
            "now": _dt_param(now),
        },
    )


def upsert_org(tx, org: OrgModel, now: datetime) -> None:
    cypher = (
        "MERGE (o:Org {id: $id}) "
        "SET o.name = $name, o.domain = $domain, o.sector = $sector, "
        "o.source_uri = $source_uri, o.last_seen = datetime($now)"
    )
    tx.run(
        cypher,
        {
            "id": org.id,
            "name": org.name or org.id,
            "domain": org.domain,
            "sector": org.sector,
            "source_uri": org.source_uri,
            "now": _dt_param(now),
        },
    )


def upsert_person(tx, person: PersonModel, org_id: str | None, now: datetime) -> None:
    cypher = (
        "MERGE (p:Person {id: $id}) "
        "SET p.name = $name, p.title = $title, p.email = $email, p.org_id = $org_id, "
        "p.influence_score = $influence_score, p.source_uri = $source_uri, p.last_seen = datetime($now) "
        "WITH p "
        "OPTIONAL MATCH (o:Org {id: $org_id}) "
        "FOREACH (_ IN CASE WHEN o IS NULL THEN [] ELSE [1] END | "
        "    MERGE (p)-[r:WORKS_FOR]->(o) "
        "    SET r.source_uri = $source_uri, r.last_seen = datetime($now)"
        ")"
    )
    tx.run(
        cypher,
        {
            "id": person.id,
            "name": person.name or person.id,
            "title": person.title,
            "email": person.email,
            "org_id": org_id,
            "influence_score": person.influence_score,
            "source_uri": person.source_uri,
            "now": _dt_param(now),
        },
    )


def upsert_project(tx, project: ProjectModel, now: datetime) -> None:
    cypher = (
        "MERGE (p:Project {id: $id}) "
        "SET p.name = $name, p.status = $status, p.source_uri = $source_uri, p.last_seen = datetime($now)"
    )
    tx.run(
        cypher,
        {
            "id": project.id,
            "name": project.name or project.id,
            "status": project.status,
            "source_uri": project.source_uri,
            "now": _dt_param(now),
        },
    )


def upsert_contract(tx, contract: ContractModel, org_ids: Iterable[str], now: datetime) -> None:
    cypher = (
        "MERGE (c:Contract {id: $id}) "
        "SET c.name = $name, c.sap_id = $sap_id, c.value = $value, "
        "c.start_date = CASE WHEN $start_date IS NULL THEN NULL ELSE date($start_date) END, "
        "c.end_date = CASE WHEN $end_date IS NULL THEN NULL ELSE date($end_date) END, "
        "c.source_uri = $source_uri, c.last_seen = datetime($now) "
        "WITH c UNWIND $org_ids AS oid "
        "MATCH (o:Org {id: oid}) "
        "MERGE (o)-[r:PARTY_TO]->(c) "
        "SET r.source_uri = $source_uri, r.last_seen = datetime($now)"
    )
    tx.run(
        cypher,
        {
            "id": contract.id,
            "name": contract.name or contract.id,
            "sap_id": contract.sap_id,
            "value": contract.value,
            "start_date": contract.start_date.isoformat() if contract.start_date else None,
            "end_date": contract.end_date.isoformat() if contract.end_date else None,
            "source_uri": contract.source_uri,
            "org_ids": list(org_ids),
            "now": _dt_param(now),
        },
    )


def upsert_topic(tx, topic: TopicModel, now: datetime) -> None:
    cypher = (
        "MERGE (t:Topic {id: $id}) "
        "SET t.name = $name, t.source_uri = $source_uri, t.last_seen = datetime($now)"
    )
    tx.run(
        cypher,
        {
            "id": topic.id,
            "name": topic.name or topic.id,
            "source_uri": topic.source_uri,
            "now": _dt_param(now),
        },
    )


def upsert_commitment(
    tx,
    commitment: CommitmentModel,
    owner_id: str,
    project_id: str | None,
    now: datetime,
) -> None:
    cypher = (
        "MERGE (c:Commitment {id: $id}) "
        "SET c.text = $text, c.due_date = CASE WHEN $due_date IS NULL THEN NULL ELSE date($due_date) END, "
        "c.status = $status, c.source_uri = $source_uri, c.last_seen = datetime($now) "
        "WITH c MATCH (p:Person {id: $owner_id}) "
        "MERGE (p)-[r:MADE]->(c) "
        "SET r.source_uri = $source_uri, r.last_seen = datetime($now) "
        "WITH c "
        "OPTIONAL MATCH (pr:Project {id: $project_id}) "
        "FOREACH (_ IN CASE WHEN pr IS NULL THEN [] ELSE [1] END | "
        "    MERGE (c)-[rp:RELATES_TO]->(pr) "
        "    SET rp.source_uri = $source_uri, rp.last_seen = datetime($now)"
        ") "
        "WITH c "
        "OPTIONAL MATCH (ct:Contract {id: $contract_id}) "
        "FOREACH (_ IN CASE WHEN ct IS NULL THEN [] ELSE [1] END | "
        "    MERGE (c)-[rc:RELATES_TO]->(ct) "
        "    SET rc.source_uri = $source_uri, rc.last_seen = datetime($now)"
        ")"
    )
    tx.run(
        cypher,
        {
            "id": commitment.id,
            "text": commitment.text,
            "status": commitment.status,
            "due_date": commitment.due_date.isoformat() if commitment.due_date else None,
            "owner_id": owner_id,
            "project_id": project_id,
            "contract_id": commitment.relates_to_contract_id,
            "source_uri": commitment.source_uri,
            "now": _dt_param(now),
        },
    )


def upsert_interaction(
    tx,
    interaction: InteractionModel,
    mentions: Sequence[str],
    now: datetime,
) -> None:
    cypher = (
        "MERGE (i:Interaction {id: $id}) "
        "SET i.type = $type, i.at = datetime($at), i.sentiment = $sentiment, "
        "i.summary = $summary, i.source_uri = $source_uri, i.last_seen = datetime($now) "
        "WITH i UNWIND $mentions AS m "
        "MATCH (n {id: m}) "
        "MERGE (i)-[r:MENTIONS]->(n) "
        "SET r.source_uri = $source_uri, r.last_seen = datetime($now)"
    )
    tx.run(
        cypher,
        {
            "id": interaction.id,
            "type": interaction.type,
            "at": _dt_param(interaction.at or now),
            "sentiment": interaction.sentiment if interaction.sentiment is not None else 0.0,
            "summary": interaction.summary or "",
            "source_uri": interaction.source_uri,
            "mentions": list(mentions),
            "now": _dt_param(now),
        },
    )


def upsert_relationship(tx, rel: RelationshipModel, source_uri: str, now: datetime) -> None:
    if rel.rel not in _ALLOWED_RELATIONSHIPS:
        raise ValueError(f"Unsupported relationship type: {rel.rel}")

    src = "(src" + (f":{rel.src_label}" if rel.src_label else "") + " {id: $src})"
    dst = "(dst" + (f":{rel.dst_label}" if rel.dst_label else "") + " {id: $dst})"
    cypher = (
        f"MATCH {src} MATCH {dst} "
        f"MERGE (src)-[r:{rel.rel}]->(dst) "
        "SET r.source_uri = $source_uri, r.last_seen = datetime($now)"
    )
    params: dict[str, Any] = {
        "src": rel.src,
        "dst": rel.dst,
        "source_uri": source_uri,
        "now": _dt_param(now),
    }
    if rel.properties:
        cypher += " SET r += $props"
        params["props"] = rel.properties
    tx.run(cypher, params)


def upsert_interaction_bundle(tx, bundle: InteractionBundle, now: datetime) -> None:
    source_uri = bundle.interaction.source_uri

    for concept in (
        bundle.entities.stakeholder_types
        + bundle.entities.risk_categories
        + bundle.entities.topic_groups
    ):
        concept.source_uri = concept.source_uri or source_uri
        upsert_concept(tx, concept, now)

    for org in bundle.entities.orgs:
        org.source_uri = org.source_uri or source_uri
        upsert_org(tx, org, now)

    for person in bundle.entities.persons:
        person.source_uri = person.source_uri or source_uri
        upsert_person(tx, person, person.org_id, now)

    for project in bundle.entities.projects:
        project.source_uri = project.source_uri or source_uri
        upsert_project(tx, project, now)

    for contract in bundle.entities.contracts:
        contract.source_uri = contract.source_uri or source_uri
        upsert_contract(tx, contract, contract.org_ids, now)

    for topic in bundle.entities.topics:
        topic.source_uri = topic.source_uri or source_uri
        upsert_topic(tx, topic, now)

    for commitment in bundle.entities.commitments:
        commitment.source_uri = commitment.source_uri or source_uri
        upsert_commitment(
            tx,
            commitment,
            commitment.owner_id,
            commitment.relates_to_project_id,
            now,
        )

    mention_ids = [
        rel.dst
        for rel in bundle.relationships
        if rel.rel == "MENTIONS" and rel.src == bundle.interaction.id
    ]
    upsert_interaction(tx, bundle.interaction, mention_ids, now)

    for rel in bundle.relationships:
        if rel.rel == "MENTIONS":
            continue
        rel.source_uri = rel.source_uri or source_uri
        upsert_relationship(tx, rel, rel.source_uri, now)
