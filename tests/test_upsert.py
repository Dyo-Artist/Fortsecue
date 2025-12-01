import pathlib
import sys
from datetime import datetime, timezone

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


def test_upsert_person_with_work_relationship():
    tx = FakeTx()
    now = datetime(2024, 1, 2, tzinfo=timezone.utc)
    person = upsert.PersonModel(id="p1", name="Alice", org_id="org1", title="CTO", source_uri="src")

    upsert.upsert_person(tx, person, person.org_id, now)

    cypher, params = tx.calls[0]
    assert "WORKS_FOR" in cypher
    assert params["org_id"] == "org1"
    assert params["now"] == now.isoformat()


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
        ),
        relationships=[
            upsert.RelationshipModel(src="i1", dst="p1", rel="MENTIONS"),
            upsert.RelationshipModel(src="p1", dst="pr1", rel="INVOLVED_IN"),
        ],
    )

    upsert.upsert_interaction_bundle(tx, bundle, now)

    assert len(tx.calls) >= 7
    assert tx.calls[0][1]["id"] == "org1"  # orgs first
    assert tx.calls[1][1]["id"] == "p1"  # persons next
    assert any("MENTIONS" in call[0] for call in tx.calls)
    assert any("INVOLVED_IN" in call[0] for call in tx.calls)
