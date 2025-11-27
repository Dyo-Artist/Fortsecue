from __future__ import annotations

import os
from typing import Any, Dict, Optional

try:
    from neo4j import Driver, GraphDatabase  # type: ignore
except Exception:  # pragma: no cover - neo4j is optional for tests
    Driver = None  # type: ignore
    GraphDatabase = None  # type: ignore


class GraphUnavailable(Exception):
    """Raised when the graph database is unavailable."""


NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")

_driver: Driver | None = None
if GraphDatabase and Driver:
    try:
        _driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    except Exception:  # pragma: no cover - unreachable without neo4j
        _driver = None


def get_driver() -> Driver | None:
    """
    Return the Neo4j driver instance if configured, otherwise None.
    """

    return _driver


def run_query(query: str, params: Optional[Dict[str, Any]] = None) -> Any:
    """Run a Cypher query against the configured Neo4j instance."""
    if _driver is None:
        raise GraphUnavailable("neo4j_unavailable")
    try:
        with _driver.session(database=NEO4J_DATABASE or None) as session:
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
        raise GraphUnavailable("neo4j_unavailable")
    try:
        run_query("RETURN 1")
        return {"ok": True, "reason": "ok"}
    except GraphUnavailable as exc:
        return {"ok": False, "reason": str(exc) or "neo4j_unavailable"}


if _driver is not None:
    try:  # pragma: no cover - executed on import
        ensure_indexes()
    except Exception:
        # Index creation failure shouldn't block application start
        pass
