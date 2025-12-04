import pathlib
import sys
from datetime import date, datetime, timezone

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from logos.graphio import upsert


class FakeTx:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def run(self, cypher: str, params: dict | None = None):
        self.calls.append((cypher, params or {}))
        return []


def test_upsert_org_sets_provenance():
    tx = FakeTx()
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    org = upsert.OrgModel(id="org1", name="Acme", domain="acme.com", sector="tech", source_uri="uri")

    upsert.upsert_org(tx, org, now)

    cypher, params = tx.calls[0]
    assert "MERGE (o:Org" in cypher
    assert params["id"] == "org1"
    assert params["domain"] == "acme.com"
    assert params["now"] == now.isoformat()


def test_upsert_org_links_category_to_concept():
    tx = FakeTx()
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    org = upsert.OrgModel(
        id="org1",
        name="Acme",
        category="org_category_energy",
        source_uri="uri",
    )

    upsert.upsert_org(tx, org, now)

    cypher, params = tx.calls[0]
    assert "INSTANCE_OF" in cypher
    assert "OPTIONAL MATCH (c:Concept" in cypher
    assert params["category"] == "org_category_energy"


def test_upsert_concept_sets_kind_and_metadata():
    tx = FakeTx()
    now = datetime(2024, 2, 1, tzinfo=timezone.utc)
    concept = upsert.ConceptModel(
        id="stakeholder_type_community",
        kind="StakeholderType",
        name="Community",
        metadata={"priority": "high"},
        source_uri="src",
    )

    upsert.upsert_concept(tx, concept, now)

    cypher, params = tx.calls[0]
    assert "MERGE (c:Concept" in cypher
    assert params["id"] == "stakeholder_type_community"
    assert params["kind"] == "StakeholderType"
    assert params["metadata"] == {"priority": "high"}
    assert params["now"] == now.isoformat()


def test_upsert_person_with_work_relationship():
    tx = FakeTx()
    now = datetime(2024, 1, 2, tzinfo=timezone.utc)
    person = upsert.PersonModel(id="p1", name="Alice", org_id="org1", title="CTO", source_uri="src")

    upsert.upsert_person(tx, person, person.org_id, now)

    cypher, params = tx.calls[0]
    assert "WORKS_FOR" in cypher
    assert params["org_id"] == "org1"
    assert params["now"] == now.isoformat()


def test_upsert_person_links_type_to_concept():
    tx = FakeTx()
    now = datetime(2024, 1, 2, tzinfo=timezone.utc)
    person = upsert.PersonModel(
        id="p1",
        name="Alice",
        type="stakeholder_type_community",
        source_uri="src",
    )

    upsert.upsert_person(tx, person, person.org_id, now)

    cypher, params = tx.calls[0]
    assert "INSTANCE_OF" in cypher
    assert "OPTIONAL MATCH (c:Concept" in cypher
    assert params["person_type"] == "stakeholder_type_community"


def test_upsert_interaction_bundle_orders_entities():
    tx = FakeTx()
    now = datetime(2024, 1, 3, tzinfo=timezone.utc)
    bundle = upsert.InteractionBundle(
        interaction=upsert.InteractionModel(
            id="i1",
            type="email",
            at=now,
            sentiment=0.5,
            summary="hi",
            source_uri="src",
        ),
        entities=upsert.EntitiesModel(
            stakeholder_types=[upsert.ConceptModel(id="st1", kind="StakeholderType", name="Community")],
            risk_categories=[upsert.ConceptModel(id="rc1", kind="RiskCategory", name="Safety")],
            topic_groups=[upsert.ConceptModel(id="tg1", kind="TopicGroup", name="Operations")],
            orgs=[upsert.OrgModel(id="org1", name="Acme")],
            persons=[upsert.PersonModel(id="p1", name="Alice", org_id="org1")],
            projects=[upsert.ProjectModel(id="pr1", name="Proj")],
            contracts=[upsert.ContractModel(id="ct1", name="Contract", org_ids=["org1"])],
            topics=[upsert.TopicModel(id="t1", name="Topic")],
            commitments=[
                upsert.CommitmentModel(
                    id="c1",
                    text="Do it",
                    person_id="p1",
                    relates_to_project_id="pr1",
                )
            ],
            risks=[
                upsert.RiskModel(
                    id="r1",
                    title="Safety risk",
                    relates_to_project_ids=["pr1"],
                    relates_to_topic_ids=["t1"],
                )
            ],
            outcomes=[
                upsert.OutcomeModel(
                    id="o1",
                    title="Outcome",
                    associated_project_ids=["pr1"],
                    results_from_risk_ids=["r1"],
                )
            ],
            issues=[
                upsert.IssueModel(
                    id="is1",
                    title="Issue",
                    relates_to_project_ids=["pr1"],
                    relates_to_topic_ids=["t1"],
                    related_risk_ids=["r1"],
                    raised_in_interaction_id="i1",
                )
            ],
        ),
        relationships=[
            upsert.RelationshipModel(src="i1", dst="p1", rel="MENTIONS"),
            upsert.RelationshipModel(src="p1", dst="pr1", rel="INVOLVED_IN"),
        ],
    )

    upsert.upsert_interaction_bundle(tx, bundle, now)

    assert len(tx.calls) >= 10
    assert "Concept" in tx.calls[0][0]
    assert tx.calls[0][1]["kind"] == "StakeholderType"
    org_call = next((params for cypher, params in tx.calls if "MERGE (o:Org" in cypher), None)
    assert org_call and org_call["id"] == "org1"
    person_call = next((params for cypher, params in tx.calls if "MERGE (p:Person" in cypher), None)
    assert person_call and person_call["id"] == "p1"
    assert any("MENTIONS" in call[0] for call in tx.calls)
    assert any("INVOLVED_IN" in call[0] for call in tx.calls)


def test_upsert_issue_links_related_entities():
    tx = FakeTx()
    now = datetime(2024, 5, 1, tzinfo=timezone.utc)
    issue = upsert.IssueModel(
        id="issue1",
        title="Dust issue",
        relates_to_project_ids=["pr1"],
        relates_to_topic_ids=["topic1"],
        related_risk_ids=["risk1"],
        raised_in_interaction_id="i1",
        severity="high",
        status="open",
    )

    upsert.upsert_issue(tx, issue, now)

    cypher, params = tx.calls[0]
    assert "Issue" in cypher
    assert "RELATED_TO" in cypher
    assert "RAISED_IN" in cypher
    assert params["project_ids"] == ["pr1"]
    assert params["topic_ids"] == ["topic1"]
    assert params["risk_ids"] == ["risk1"]
    assert params["severity"] == "high"
    assert params["now"] == now.isoformat()


def test_upsert_risk_and_outcome_relationships():
    tx = FakeTx()
    now = datetime(2024, 6, 1, tzinfo=timezone.utc)
    risk = upsert.RiskModel(
        id="risk1",
        title="Schedule slip",
        category="schedule",
        likelihood="medium",
        impact="high",
        score=0.6,
        relates_to_project_ids=["pr1"],
        relates_to_topic_ids=["topic1"],
        results_in_outcome_ids=["outcome1"],
    )
    outcome = upsert.OutcomeModel(
        id="outcome1",
        title="Delay",
        type="failure",
        realised_date=date(2024, 6, 15),
        associated_project_ids=["pr1"],
        results_from_risk_ids=["risk1"],
    )

    upsert.upsert_risk(tx, risk, now)
    upsert.upsert_outcome(tx, outcome, now)

    risk_call = next((params for cypher, params in tx.calls if "MERGE (r:Risk" in cypher), None)
    assert risk_call and risk_call["score"] == 0.6
    assert risk_call["outcome_ids"] == ["outcome1"]

    outcome_call = next((params for cypher, params in tx.calls if "MERGE (o:Outcome" in cypher), None)
    assert outcome_call and outcome_call["realised_date"] == "2024-06-15"
    assert outcome_call["risk_ids"] == ["risk1"]


def test_upsert_relationship_supports_result_of_with_explanation():
    tx = FakeTx()
    now = datetime(2024, 7, 1, tzinfo=timezone.utc)
    rel = upsert.RelationshipModel(
        src="risk2", dst="issue2", rel="RESULT_OF", properties={"explanation": "Root cause"}
    )

    upsert.upsert_relationship(tx, rel, "source://reasoning", now)

    cypher, params = tx.calls[0]
    assert "RESULT_OF" in cypher
    assert params["src"] == "risk2"
    assert params["dst"] == "issue2"
    assert params["props"]["explanation"] == "Root cause"
    assert params["now"] == now.isoformat()
