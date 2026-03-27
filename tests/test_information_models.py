from pydantic import ValidationError

from logos.information.models import (
    Belief,
    BeliefStatement,
    BeliefTerm,
    BeliefStatus,
    Evidence,
    InformationObject,
    Polarity,
    Provenance,
)


def test_information_object_accepts_embeddings_and_provenance():
    info = InformationObject(
        id="info_1",
        type="interaction_summary",
        payload={"summary": "A meeting happened."},
        provenance=Provenance(source_uri="file:///tmp/meeting.md", source_type="doc"),
        embeddings=[0.1, 0.2, 0.3],
        confidence=0.9,
    )

    assert info.type == "interaction_summary"
    assert info.provenance.source_uri == "file:///tmp/meeting.md"
    assert info.embeddings == [0.1, 0.2, 0.3]


def test_belief_and_evidence_schema_validation():
    belief = Belief(
        id="belief_1",
        statement=BeliefStatement(
            subject=BeliefTerm(ref="Person:p1"),
            predicate="WORKS_FOR",
            object=BeliefTerm(ref="Org:o1"),
        ),
        polarity=Polarity.POSITIVE,
        confidence=0.8,
        provenance=Provenance(source_uri="source://x"),
        status=BeliefStatus.CANDIDATE,
    )
    evidence = Evidence(id="e_1", belief_id=belief.id, source_uri="source://x", confidence=0.8)

    assert belief.statement.predicate == "WORKS_FOR"
    assert belief.provenance.source_uri == "source://x"
    assert evidence.belief_id == belief.id


def test_confidence_bounds_are_enforced():
    try:
        Belief(
            id="belief_bad",
            statement=BeliefStatement(
                subject=BeliefTerm(ref="A:a"),
                predicate="REL",
                object=BeliefTerm(ref="B:b"),
            ),
            confidence=1.1,
        )
    except ValidationError:
        pass
    else:  # pragma: no cover
        raise AssertionError("Belief confidence > 1.0 should fail validation")
