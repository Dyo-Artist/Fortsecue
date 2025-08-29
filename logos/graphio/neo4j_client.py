import os
from typing import Any, Dict, Optional

try:
    from neo4j import GraphDatabase  # type: ignore
except Exception:  # pragma: no cover - neo4j is optional for tests
    GraphDatabase = None  # type: ignore


class GraphUnavailable(Exception):
    """Raised when the graph database is unavailable."""


NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USER = os.getenv("NEO4J_USER")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")

_driver = None
if GraphDatabase and NEO4J_URI and NEO4J_USER and NEO4J_PASSWORD:
    try:
        _driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    except Exception:  # pragma: no cover - unreachable without neo4j
        _driver = None


def run_query(query: str, params: Optional[Dict[str, Any]] = None) -> Any:
    """Run a Cypher query against the configured Neo4j instance."""
    if _driver is None:
        raise GraphUnavailable("neo4j_unavailable")
    try:
        with _driver.session() as session:
            return session.run(query, params or {})
    except Exception as exc:  # pragma: no cover - network failure etc.
        raise GraphUnavailable("neo4j_unavailable") from exc


def ensure_indexes() -> None:
    """Ensure required constraints and indexes exist."""
    if _driver is None:
        return
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


def ping() -> Dict[str, Any]:
    """Return the availability of the graph database."""
    if _driver is None:
        return {"ok": False, "reason": "neo4j_unavailable"}
    try:
        run_query("RETURN 1")
        return {"ok": True, "reason": "neo4j_up"}
    except GraphUnavailable:
        return {"ok": False, "reason": "neo4j_unavailable"}


if _driver is not None:
    try:  # pragma: no cover - executed on import
        ensure_indexes()
    except Exception:
        # Index creation failure shouldn't block application start
        pass
