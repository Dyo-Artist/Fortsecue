from __future__ import annotations

import os
from logging import Logger, getLogger
from typing import Any, Callable, Dict, Optional

try:  # pragma: no cover - optional dependency for CI
    from neo4j import Driver, GraphDatabase, Transaction  # type: ignore
except Exception:  # pragma: no cover - neo4j optional for tests
    Driver = None  # type: ignore
    GraphDatabase = None  # type: ignore
    Transaction = Any  # type: ignore

from logos.graphio.schema_store import SchemaStore


class GraphUnavailable(Exception):
    """Raised when the graph database is unavailable."""


NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")

logger = getLogger(__name__)


class Neo4jClient:
    """Lightweight Neo4j client wrapper for LOGOS."""

    def __init__(
        self,
        uri: str = NEO4J_URI,
        user: str = NEO4J_USER,
        password: str = NEO4J_PASSWORD,
        database: str | None = NEO4J_DATABASE,
        logging: Logger | None = None,
    ) -> None:
        self._logger = logging or logger
        self._database = database
        if GraphDatabase is None or Driver is None:  # pragma: no cover - neo4j optional
            self._driver = None
        else:
            try:
                self._driver: Driver | None = GraphDatabase.driver(
                    uri, auth=(user, password)
                )
            except Exception:  # pragma: no cover - unreachable without neo4j
                self._driver = None

    @property
    def driver(self) -> Driver | None:
        return getattr(self, "_driver", None)

    @property
    def database(self) -> str | None:
        return self._database or None

    def run(self, cypher: str, params: Optional[Dict[str, Any]] = None) -> list[dict]:
        """Run a Cypher query and return materialised rows."""

        if self.driver is None:
            raise GraphUnavailable("neo4j_unavailable")
        try:
            with self.driver.session(database=self.database) as session:
                result = session.run(cypher, params or {})
                return [dict(record) for record in result]
        except Exception as exc:  # pragma: no cover - network failure etc.
            raise GraphUnavailable("neo4j_unavailable") from exc

    def run_in_tx(self, fn: Callable[[Transaction], None]) -> None:
        """Execute a callback inside a write transaction."""

        if self.driver is None:
            raise GraphUnavailable("neo4j_unavailable")
        try:
            with self.driver.session(database=self.database) as session:
                session.execute_write(fn)
        except Exception as exc:  # pragma: no cover - network failure etc.
            raise GraphUnavailable("neo4j_unavailable") from exc


_client: Neo4jClient | None = None


def _get_client() -> Neo4jClient:
    global _client
    if _client is None:
        _client = Neo4jClient()
    if _client.driver is None:
        raise GraphUnavailable("neo4j_unavailable")
    return _client


def get_driver() -> Driver | None:
    """Return the underlying driver instance."""

    try:
        return _get_client().driver
    except GraphUnavailable:
        return None


def get_client() -> Neo4jClient:
    """Expose the configured client for callers that need transactions."""

    return _get_client()


def run_query(query: str, params: Optional[Dict[str, Any]] = None) -> Any:
    """Run a Cypher query against the configured Neo4j instance."""

    client = _get_client()
    return client.run(query, params)


def ensure_indexes() -> None:
    """Ensure required constraints and indexes exist."""

    try:
        client = _get_client()
    except GraphUnavailable:
        return

    try:
        schema_store = SchemaStore(mutable=False)
        labels = list(schema_store.node_types.keys()) or [
            "Person",
            "Org",
            "Project",
            "Contract",
            "Commitment",
            "Interaction",
        ]
    except Exception:
        labels = [
            "Person",
            "Org",
            "Project",
            "Contract",
            "Commitment",
            "Interaction",
        ]
    for label in labels:
        client.run(
            "CREATE CONSTRAINT IF NOT EXISTS FOR (n:%s) REQUIRE n.id IS UNIQUE" % label,
            {},
        )
    name_index_labels = [label for label in labels if label in {"Person", "Org", "Project", "Contract", "Commitment"}]
    if name_index_labels:
        labels_literal = "','".join(name_index_labels)
        client.run(
            "CALL db.index.fulltext.createNodeIndex('logos_name_idx', ['%s'], ['name'], { ifNotExists: true })"
            % labels_literal
        )


def ping() -> Dict[str, Any]:
    """Return the availability of the graph database."""

    try:
        client = _get_client()
    except GraphUnavailable as exc:
        raise GraphUnavailable("neo4j_unavailable") from exc

    try:
        client.run("RETURN 1")
        return {"ok": True, "reason": "ok"}
    except GraphUnavailable as exc:
        return {"ok": False, "reason": str(exc) or "neo4j_unavailable"}


# Initialise on import without failing app startup
try:  # pragma: no cover - executed on import
    ensure_indexes()
except Exception:
    pass
