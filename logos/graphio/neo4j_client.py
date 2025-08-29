import os
from typing import Any, Dict, Optional

try:
    from neo4j import GraphDatabase  # type: ignore
except Exception:  # pragma: no cover - neo4j is optional for tests
    GraphDatabase = None  # type: ignore

NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USER = os.getenv("NEO4J_USER")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")

_driver = None
if GraphDatabase and NEO4J_URI and NEO4J_USER and NEO4J_PASSWORD:
    _driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


def run_query(query: str, params: Optional[Dict[str, Any]] = None) -> Any:
    """Run a Cypher query against the configured Neo4j instance."""
    if _driver is None:
        raise RuntimeError("Neo4j driver not configured")
    with _driver.session() as session:
        return session.run(query, params or {})


def ensure_indexes() -> None:
    """Ensure required constraints and indexes exist."""
    labels = [
        "Person",
        "Org",
        "Project",
        "Contract",
        "Commitment",
        "Interaction",
    ]
    for label in labels:
        run_query(
            f"CREATE CONSTRAINT {label.lower()}_id IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE"
        )
    run_query(
        "CALL db.index.fulltext.createNodeIndex('logos_name_idx', ['Person','Org','Project','Contract','Commitment'], ['name'], { ifNotExists: true })"
    )


if _driver is not None:
    try:
        ensure_indexes()
    except Exception:
        # Index creation failure shouldn't block application start
        pass
