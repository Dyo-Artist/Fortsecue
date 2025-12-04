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
    category: str | None = None
    source_uri: str | None = None


class PersonModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str | None = None
    title: str | None = None
    email: str | None = None
    org_id: str | None = None
    type: str | None = None
    influence_score: float | None = None
    source_uri: str | None = None


class AgentModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str | None = None
    role: str | None = None
    source_uri: str | None = None
    created_by: str | None = None
    updated_by: str | None = None


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


class IssueModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    title: str | None = None
    description: str | None = None
    category: str | None = None
    status: str | None = None
    severity: str | None = None
    relates_to_project_ids: list[str] = Field(default_factory=list)
    relates_to_topic_ids: list[str] = Field(default_factory=list)
    related_risk_ids: list[str] = Field(default_factory=list)
    raised_in_interaction_id: str | None = None
    source_uri: str | None = None


class RiskModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    title: str | None = None
    description: str | None = None
    category: str | None = None
    likelihood: str | float | None = None
    impact: str | float | None = None
    score: float | None = None
    status: str | None = None
    relates_to_project_ids: list[str] = Field(default_factory=list)
    relates_to_topic_ids: list[str] = Field(default_factory=list)
    results_in_outcome_ids: list[str] = Field(default_factory=list)
    identified_in_interaction_id: str | None = None
    source_uri: str | None = None


class OutcomeModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    title: str | None = None
    description: str | None = None
    type: str | None = None
    realised_date: date | None = None
    associated_project_ids: list[str] = Field(default_factory=list)
    results_from_risk_ids: list[str] = Field(default_factory=list)
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
    issues: list[IssueModel] = Field(default_factory=list)
    risks: list[RiskModel] = Field(default_factory=list)
    outcomes: list[OutcomeModel] = Field(default_factory=list)


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
    "RELATED_TO",
    "RAISED_IN",
    "IDENTIFIED_IN",
    "RESULTS_IN",
    "ASSOCIATED_WITH",
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
        "o.category = $category, o.source_uri = $source_uri, o.last_seen = datetime($now) "
        "WITH o "
        "OPTIONAL MATCH (c:Concept) WHERE c.id = $category OR c.name = $category "
        "FOREACH (_ IN CASE WHEN c IS NULL THEN [] ELSE [1] END | "
        "    MERGE (o)-[r:INSTANCE_OF]->(c) "
        "    SET r.source_uri = $source_uri, r.last_seen = datetime($now)"
        ")"
    )
    tx.run(
        cypher,
        {
            "id": org.id,
            "name": org.name or org.id,
            "domain": org.domain,
            "sector": org.sector,
            "category": org.category,
            "source_uri": org.source_uri,
            "now": _dt_param(now),
        },
    )


def upsert_person(tx, person: PersonModel, org_id: str | None, now: datetime) -> None:
    cypher = (
        "MERGE (p:Person {id: $id}) "
        "SET p.name = $name, p.title = $title, p.email = $email, p.org_id = $org_id, "
        "p.type = $person_type, p.influence_score = $influence_score, p.source_uri = $source_uri, p.last_seen = datetime($now) "
        "WITH p "
        "OPTIONAL MATCH (o:Org {id: $org_id}) "
        "FOREACH (_ IN CASE WHEN o IS NULL THEN [] ELSE [1] END | "
        "    MERGE (p)-[r:WORKS_FOR]->(o) "
        "    SET r.source_uri = $source_uri, r.last_seen = datetime($now)"
        ") "
        "WITH p "
        "OPTIONAL MATCH (c:Concept) WHERE c.id = $person_type OR c.name = $person_type "
        "FOREACH (_ IN CASE WHEN c IS NULL THEN [] ELSE [1] END | "
        "    MERGE (p)-[rc:INSTANCE_OF]->(c) "
        "    SET rc.source_uri = $source_uri, rc.last_seen = datetime($now)"
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
            "person_type": person.type,
            "influence_score": person.influence_score,
            "source_uri": person.source_uri,
        "now": _dt_param(now),
    },
    )


def upsert_agent_assist(tx, agent: AgentModel, user: PersonModel, now: datetime) -> None:
    cypher = (
        "MERGE (a:Agent {id: $agent_id}) "
        "SET a.name = $agent_name, a.role = $agent_role, a.source_uri = $source_uri, "
        "a.created_by = coalesce(a.created_by, $actor_id), a.updated_by = $actor_id, "
        "a.created_at = coalesce(a.created_at, datetime($now)), a.updated_at = datetime($now), "
        "a.first_seen_at = coalesce(a.first_seen_at, datetime($now)), a.last_seen_at = datetime($now) "
        "WITH a "
        "MERGE (u:Person {id: $user_id}) "
        "ON CREATE SET u.name = $user_name, u.source_uri = $source_uri, "
        "u.created_by = $actor_id, u.updated_by = $actor_id, "
        "u.created_at = datetime($now), u.updated_at = datetime($now), "
        "u.first_seen_at = datetime($now), u.last_seen_at = datetime($now) "
        "ON MATCH SET u.updated_at = datetime($now), u.last_seen_at = datetime($now), u.updated_by = $actor_id "
        "MERGE (a)-[r:ASSISTS]->(u) "
        "SET r.source_uri = $source_uri, r.created_by = coalesce(r.created_by, $actor_id), "
        "r.updated_by = $actor_id, r.created_at = coalesce(r.created_at, datetime($now)), "
        "r.updated_at = datetime($now), r.first_seen_at = coalesce(r.first_seen_at, datetime($now)), "
        "r.last_seen_at = datetime($now)"
    )
    tx.run(
        cypher,
        {
            "agent_id": agent.id,
            "agent_name": agent.name or agent.id,
            "agent_role": agent.role,
            "user_id": user.id,
            "user_name": user.name or user.id,
            "source_uri": agent.source_uri or user.source_uri,
            "actor_id": agent.updated_by or agent.created_by or agent.id,
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


def upsert_issue(tx, issue: IssueModel, now: datetime) -> None:
    cypher = (
        "MERGE (i:Issue {id: $id}) "
        "SET i.title = $title, i.description = $description, i.category = $category, "
        "i.status = $status, i.severity = $severity, i.source_uri = $source_uri, i.last_seen = datetime($now) "
        "WITH i "
        "FOREACH (pid IN $project_ids | "
        "    OPTIONAL MATCH (p:Project {id: pid}) "
        "    FOREACH (_ IN CASE WHEN p IS NULL THEN [] ELSE [1] END | "
        "        MERGE (i)-[rp:RELATED_TO]->(p) "
        "        SET rp.source_uri = $source_uri, rp.last_seen = datetime($now)"
        "    )"
        ") "
        "WITH i "
        "FOREACH (tid IN $topic_ids | "
        "    OPTIONAL MATCH (t:Topic {id: tid}) "
        "    FOREACH (_ IN CASE WHEN t IS NULL THEN [] ELSE [1] END | "
        "        MERGE (i)-[rt:RELATED_TO]->(t) "
        "        SET rt.source_uri = $source_uri, rt.last_seen = datetime($now)"
        "    )"
        ") "
        "WITH i "
        "FOREACH (rid IN $risk_ids | "
        "    OPTIONAL MATCH (rk:Risk {id: rid}) "
        "    FOREACH (_ IN CASE WHEN rk IS NULL THEN [] ELSE [1] END | "
        "        MERGE (i)-[rr:RELATED_TO]->(rk) "
        "        SET rr.source_uri = $source_uri, rr.last_seen = datetime($now)"
        "    )"
        ") "
        "WITH i "
        "OPTIONAL MATCH (inter:Interaction {id: $raised_in}) "
        "FOREACH (_ IN CASE WHEN inter IS NULL THEN [] ELSE [1] END | "
        "    MERGE (i)-[ri:RAISED_IN]->(inter) "
        "    SET ri.source_uri = $source_uri, ri.last_seen = datetime($now)"
        ")"
    )
    tx.run(
        cypher,
        {
            "id": issue.id,
            "title": issue.title or issue.id,
            "description": issue.description,
            "category": issue.category,
            "status": issue.status,
            "severity": issue.severity,
            "source_uri": issue.source_uri,
            "project_ids": list(issue.relates_to_project_ids),
            "topic_ids": list(issue.relates_to_topic_ids),
            "risk_ids": list(issue.related_risk_ids),
            "raised_in": issue.raised_in_interaction_id,
            "now": _dt_param(now),
        },
    )


def upsert_risk(tx, risk: RiskModel, now: datetime) -> None:
    cypher = (
        "MERGE (r:Risk {id: $id}) "
        "SET r.title = $title, r.description = $description, r.category = $category, "
        "r.likelihood = $likelihood, r.impact = $impact, r.score = $score, r.status = $status, "
        "r.source_uri = $source_uri, r.last_seen = datetime($now) "
        "WITH r "
        "FOREACH (pid IN $project_ids | "
        "    OPTIONAL MATCH (p:Project {id: pid}) "
        "    FOREACH (_ IN CASE WHEN p IS NULL THEN [] ELSE [1] END | "
        "        MERGE (r)-[rp:RELATED_TO]->(p) "
        "        SET rp.source_uri = $source_uri, rp.last_seen = datetime($now)"
        "    )"
        ") "
        "WITH r "
        "FOREACH (tid IN $topic_ids | "
        "    OPTIONAL MATCH (t:Topic {id: tid}) "
        "    FOREACH (_ IN CASE WHEN t IS NULL THEN [] ELSE [1] END | "
        "        MERGE (r)-[rt:RELATED_TO]->(t) "
        "        SET rt.source_uri = $source_uri, rt.last_seen = datetime($now)"
        "    )"
        ") "
        "WITH r "
        "FOREACH (oid IN $outcome_ids | "
        "    OPTIONAL MATCH (o:Outcome {id: oid}) "
        "    FOREACH (_ IN CASE WHEN o IS NULL THEN [] ELSE [1] END | "
        "        MERGE (r)-[ro:RESULTS_IN]->(o) "
        "        SET ro.source_uri = $source_uri, ro.last_seen = datetime($now)"
        "    )"
        ") "
        "WITH r "
        "OPTIONAL MATCH (inter:Interaction {id: $identified_in}) "
        "FOREACH (_ IN CASE WHEN inter IS NULL THEN [] ELSE [1] END | "
        "    MERGE (r)-[ri:IDENTIFIED_IN]->(inter) "
        "    SET ri.source_uri = $source_uri, ri.last_seen = datetime($now)"
        ")"
    )
    tx.run(
        cypher,
        {
            "id": risk.id,
            "title": risk.title or risk.id,
            "description": risk.description,
            "category": risk.category,
            "likelihood": risk.likelihood,
            "impact": risk.impact,
            "score": risk.score,
            "status": risk.status,
            "source_uri": risk.source_uri,
            "project_ids": list(risk.relates_to_project_ids),
            "topic_ids": list(risk.relates_to_topic_ids),
            "outcome_ids": list(risk.results_in_outcome_ids),
            "identified_in": risk.identified_in_interaction_id,
            "now": _dt_param(now),
        },
    )


def upsert_outcome(tx, outcome: OutcomeModel, now: datetime) -> None:
    cypher = (
        "MERGE (o:Outcome {id: $id}) "
        "SET o.title = $title, o.description = $description, o.type = $type, "
        "o.realised_date = CASE WHEN $realised_date IS NULL THEN NULL ELSE date($realised_date) END, "
        "o.source_uri = $source_uri, o.last_seen = datetime($now) "
        "WITH o "
        "FOREACH (pid IN $project_ids | "
        "    OPTIONAL MATCH (p:Project {id: pid}) "
        "    FOREACH (_ IN CASE WHEN p IS NULL THEN [] ELSE [1] END | "
        "        MERGE (o)-[ra:ASSOCIATED_WITH]->(p) "
        "        SET ra.source_uri = $source_uri, ra.last_seen = datetime($now)"
        "    )"
        ") "
        "WITH o "
        "FOREACH (rid IN $risk_ids | "
        "    OPTIONAL MATCH (r:Risk {id: rid}) "
        "    FOREACH (_ IN CASE WHEN r IS NULL THEN [] ELSE [1] END | "
        "        MERGE (r)-[rr:RESULTS_IN]->(o) "
        "        SET rr.source_uri = $source_uri, rr.last_seen = datetime($now)"
        "    )"
        ")"
    )
    tx.run(
        cypher,
        {
            "id": outcome.id,
            "title": outcome.title or outcome.id,
            "description": outcome.description,
            "type": outcome.type,
            "realised_date": outcome.realised_date.isoformat() if outcome.realised_date else None,
            "source_uri": outcome.source_uri,
            "project_ids": list(outcome.associated_project_ids),
            "risk_ids": list(outcome.results_from_risk_ids),
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

    for risk in bundle.entities.risks:
        risk.source_uri = risk.source_uri or source_uri
        upsert_risk(tx, risk, now)

    for outcome in bundle.entities.outcomes:
        outcome.source_uri = outcome.source_uri or source_uri
        upsert_outcome(tx, outcome, now)

    for issue in bundle.entities.issues:
        issue.source_uri = issue.source_uri or source_uri
        upsert_issue(tx, issue, now)

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
