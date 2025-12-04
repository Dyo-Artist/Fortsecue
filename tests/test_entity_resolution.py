from logos.normalise.resolution import GraphEntityResolver, resolve_preview_from_graph


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

    person = resolved["entities"]["persons"][0]
    assert person["id"] == "p_alice"
    assert person["org_id"] == "o_acme"
    assert person["canonical_id"] == "p_alice"

    project = resolved["entities"]["projects"][0]
    assert project["id"] == "pr_apollo"
    assert project["canonical_id"] == "pr_apollo"

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
