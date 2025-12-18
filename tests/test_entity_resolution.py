from logos.normalise.resolution import GraphEntityResolver, reassign_preview_identities, resolve_preview_from_graph


class StubClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    def run(self, cypher: str, params=None):
        self.calls.append((cypher, params or {}))
        if self.responses:
            return self.responses.pop(0)
        return []


def test_resolve_preview_updates_entities_and_relationships():
    preview = {
        "entities": {
            "orgs": [{"id": "org_temp", "name": "Acme Pty Ltd", "domain": "acme.com"}],
            "persons": [
                {
                    "id": "p_temp",
                    "name": "Alice Smith",
                    "email": "alice@acme.com",
                    "org_id": "org_temp",
                }
            ],
            "projects": [{"id": "proj_temp", "name": "Apollo"}],
        },
        "relationships": [
            {"src": "p_temp", "dst": "org_temp", "rel": "WORKS_FOR"},
            {"src": "proj_temp", "dst": "org_temp", "rel": "RELATED_TO"},
        ],
    }

    responses = [
        [
            {"id": "o_acme", "name": "Acme Pty Ltd", "domain": "acme.com"},
        ],
        [
            {
                "id": "p_alice",
                "name": "Alice Smith",
                "email": "alice@acme.com",
                "org_id": "o_acme",
                "org_name": "Acme Pty Ltd",
            }
        ],
        [
            {
                "id": "pr_apollo",
                "name": "Apollo",
            }
        ],
    ]
    client = StubClient(responses)
    resolved = resolve_preview_from_graph(preview, client_factory=lambda: client)

    org = resolved["entities"]["orgs"][0]
    assert org["id"] == "o_acme"
    assert org["canonical_id"] == "o_acme"
    assert org["temp_id"] == "org_temp"
    assert org["resolution_status"] == "resolved"
    assert org["identity_candidates"][0]["id"] == "o_acme"

    person = resolved["entities"]["persons"][0]
    assert person["id"] == "p_alice"
    assert person["org_id"] == "o_acme"
    assert person["canonical_id"] == "p_alice"
    assert person["alternates"] == []
    assert person["resolution_status"] == "resolved"

    project = resolved["entities"]["projects"][0]
    assert project["id"] == "pr_apollo"
    assert project["canonical_id"] == "pr_apollo"

    assert resolved.get("resolution_log", []) == []

    updated_relationships = {(rel["src"], rel["dst"]) for rel in resolved.get("relationships", [])}
    assert ("p_alice", "o_acme") in updated_relationships
    assert ("pr_apollo", "o_acme") in updated_relationships


def test_low_confidence_person_does_not_resolve():
    preview = {
        "entities": {
            "persons": [{"id": "p_temp", "name": "Bob", "org_id": None}],
        },
        "relationships": [],
    }
    resolver = GraphEntityResolver(lambda _q, _p: [{"id": "p_existing", "name": "Bob"}])
    resolved = resolver.resolve_preview(preview)

    person = resolved["entities"]["persons"][0]
    assert person.get("canonical_id") is None
    assert person["id"] == "p_temp"
    assert person.get("best_guess_id") == "p_existing"
    assert person.get("resolution_status") == "ambiguous"
    assert resolved.get("resolution_log")


def test_similarity_thresholds_used_for_partial_match():
    preview = {
        "entities": {
            "persons": [
                {
                    "id": "p_temp",
                    "name": "Alice Smyth",
                }
            ],
        },
        "relationships": [],
    }

    rules = {"person": {"name_only_score": 0.95, "min_confidence": 0.9}}
    thresholds = {"defaults": {"name_similarity": 0.8}}
    resolver = GraphEntityResolver(
        lambda _q, _p: [
            {
                "id": "p_alice",
                "name": "Alice Smith",
            }
        ],
        rules=rules,
        thresholds=thresholds,
    )

    resolved = resolver.resolve_preview(preview)
    person = resolved["entities"]["persons"][0]
    assert person["canonical_id"] == "p_alice"
    assert person["id"] == "p_alice"
    assert person.get("resolution_status") == "resolved"


def test_context_boosts_candidate_and_retains_alternates():
    preview = {
        "context": {"project": {"id": "pr_context"}},
        "entities": {
            "persons": [
                {
                    "id": "p_temp",
                    "name": "Ryan",
                }
            ],
        },
        "relationships": [],
    }

    rules = {
        "defaults": {"min_confidence": 0.8, "candidate_floor": 0.1, "context": {"project_score": 0.3}},
        "person": {"name_only_score": 0.6, "min_confidence": 0.8, "context": {"project_score": 0.3}},
    }
    thresholds = {"defaults": {"name_similarity": 1.0, "project_similarity": 0.85}}
    resolver = GraphEntityResolver(
        lambda _q, _p: [
            {"id": "p_context", "name": "Ryan", "project_ids": ["pr_context"]},
            {"id": "p_else", "name": "Ryan", "project_ids": ["pr_other"]},
        ],
        rules=rules,
        thresholds=thresholds,
    )

    resolved = resolver.resolve_preview(preview)
    person = resolved["entities"]["persons"][0]
    assert person["canonical_id"] == "p_context"
    assert person["id"] == "p_context"
    assert any(candidate["id"] == "p_else" for candidate in person.get("alternates", []))
    assert resolved.get("resolution_log", []) == []


def test_reassign_preview_identities_updates_relationships_and_history():
    preview = {
        "entities": {
            "persons": [
                {
                    "id": "p_old",
                    "canonical_id": "p_old",
                    "identity_candidates": [
                        {"id": "p_old", "score": 0.9},
                        {"id": "p_new", "score": 0.85},
                    ],
                }
            ],
        },
        "relationships": [
            {"src": "p_old", "dst": "o_acme", "rel": "WORKS_FOR"},
        ],
    }

    reassigned = reassign_preview_identities(preview, {"p_old": "p_new"})
    person = reassigned["entities"]["persons"][0]
    assert person["id"] == "p_new"
    assert person["canonical_id"] == "p_new"
    assert any(entry.get("status") == "reassigned" for entry in person.get("identity_history", []))

    updated_relationships = reassigned.get("relationships", [])
    assert updated_relationships[0]["src"] == "p_new"
    assert any(log.get("category") == "reassignment" for log in reassigned.get("resolution_log", []))
