from __future__ import annotations

import hashlib
import math
import random
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Protocol

from logos.graphio.neo4j_client import Neo4jClient, get_client
from logos.graphio.schema_store import SchemaStore
from logos.learning.embeddings.hash_utils import hash_graph_content, hash_text_content


class TextEmbeddingBackend(Protocol):
    model_name: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class GraphEmbeddingBackend(Protocol):
    model_name: str

    def embed(self, node_ids: list[str], edges: list[tuple[str, str]]) -> dict[str, list[float]]: ...


class LocalSentenceEmbeddingBackend:
    """Local text embedding backend using sentence-transformers when available."""

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2", dimensions: int = 32) -> None:
        self.model_name = model_name
        self._dimensions = max(8, dimensions)
        self._model = None
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore

            self._model = SentenceTransformer(model_name)
        except Exception:
            self._model = None

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self._model is not None:
            vectors = self._model.encode(texts, normalize_embeddings=True)
            return [list(map(float, vector)) for vector in vectors]
        return [_hash_text_embedding(text, self._dimensions) for text in texts]


class Node2VecGraphEmbeddingBackend:
    """Graph embeddings via node2vec, with deterministic local fallback."""

    def __init__(self, *, dimensions: int = 16, walk_length: int = 12, num_walks: int = 25, seed: int = 42) -> None:
        self.dimensions = max(8, dimensions)
        self.walk_length = max(4, walk_length)
        self.num_walks = max(4, num_walks)
        self.seed = seed
        self.model_name = f"node2vec-local-d{self.dimensions}"

    def embed(self, node_ids: list[str], edges: list[tuple[str, str]]) -> dict[str, list[float]]:
        unique_nodes = sorted(set(node_ids))
        if not unique_nodes:
            return {}
        try:
            from node2vec import Node2Vec  # type: ignore
            import networkx as nx  # type: ignore

            graph = nx.Graph()
            graph.add_nodes_from(unique_nodes)
            graph.add_edges_from(edges)
            worker_count = 1
            model = Node2Vec(
                graph,
                dimensions=self.dimensions,
                walk_length=self.walk_length,
                num_walks=self.num_walks,
                workers=worker_count,
                seed=self.seed,
                quiet=True,
            )
            fitted = model.fit(window=5, min_count=1, batch_words=8, seed=self.seed)
            embeddings: dict[str, list[float]] = {}
            for node_id in unique_nodes:
                key = str(node_id)
                vector = fitted.wv[key]
                embeddings[key] = [float(v) for v in vector]
            return embeddings
        except Exception:
            return _deterministic_graph_embedding(unique_nodes, edges, self.dimensions, self.seed)


class EmbeddingService:
    def __init__(
        self,
        *,
        client: Neo4jClient | None = None,
        schema_store: SchemaStore | None = None,
        text_backend: TextEmbeddingBackend | None = None,
        graph_backend: GraphEmbeddingBackend | None = None,
    ) -> None:
        self._client = client or get_client()
        self._schema_store = schema_store or SchemaStore(mutable=False)
        self._text_backend = text_backend or LocalSentenceEmbeddingBackend()
        self._graph_backend = graph_backend or Node2VecGraphEmbeddingBackend()

    def refresh_embeddings(self, *, seed: int = 42, updated_at: datetime | None = None) -> dict[str, Any]:
        now = updated_at or datetime.now(timezone.utc)
        concept_label = self._schema_store.get_schema_convention("concept_label", "Concept") or "Concept"

        text_updated = self._refresh_text_embeddings(now=now, concept_label=concept_label)
        graph_updated = self._refresh_concept_graph_embeddings(now=now, concept_label=concept_label, seed=seed)

        return {
            "text_embeddings_updated": text_updated,
            "graph_embeddings_updated": graph_updated,
            "text_embedding_model": self._text_backend.model_name,
            "graph_embedding_model": self._graph_backend.model_name,
        }

    def _refresh_text_embeddings(self, *, now: datetime, concept_label: str) -> int:
        labels = sorted(set(self._schema_store.node_types.keys()) | {concept_label})
        updated = 0
        for label in labels:
            records = self._fetch_nodes(label)
            if not records:
                continue
            payload: list[tuple[str, Mapping[str, Any], str]] = []
            for record in records:
                node_id = str(record.get("id") or "").strip()
                props = record.get("props") if isinstance(record.get("props"), Mapping) else {}
                if not node_id or not isinstance(props, Mapping):
                    continue
                text = _select_text_fields(props)
                if text:
                    payload.append((node_id, props, text))
            if not payload:
                continue
            payload.sort(key=lambda item: item[0])
            vectors = self._text_backend.embed([item[2] for item in payload])
            for (node_id, props, _), vector in zip(payload, vectors, strict=False):
                content_hash = hash_text_content(_select_text_fields(props))
                if self._upsert_embedding(
                    label=label,
                    node_id=node_id,
                    props=props,
                    embedding_field="embedding_text",
                    embedding=vector,
                    model_name=self._text_backend.model_name,
                    model_version=self._text_backend.model_name,
                    content_hash=content_hash,
                    now=now,
                ):
                    updated += 1
        return updated

    def _refresh_concept_graph_embeddings(self, *, now: datetime, concept_label: str, seed: int) -> int:
        concept_rows = self._fetch_nodes(concept_label)
        if not concept_rows:
            return 0
        node_ids = sorted(str(row.get("id")) for row in concept_rows if row.get("id"))
        props_by_id: dict[str, Mapping[str, Any]] = {}
        for row in concept_rows:
            node_id = str(row.get("id") or "")
            props = row.get("props") if isinstance(row.get("props"), Mapping) else {}
            if node_id:
                props_by_id[node_id] = props
        edge_rows = self._client.run(
            f"MATCH (a:{concept_label})-[r]-(b:{concept_label}) WHERE a.id <> b.id RETURN a.id AS src, b.id AS dst"
        )
        edges = [
            (str(row["src"]), str(row["dst"]))
            for row in edge_rows
            if row.get("src") and row.get("dst")
        ]
        neighbours_by_id: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
        for src, dst in edges:
            neighbours_by_id.setdefault(src, set()).add(dst)
            neighbours_by_id.setdefault(dst, set()).add(src)

        graph_backend = self._graph_backend
        if isinstance(graph_backend, Node2VecGraphEmbeddingBackend):
            graph_backend.seed = seed
        embeddings = graph_backend.embed(node_ids, edges)
        updated = 0
        for node_id in sorted(embeddings.keys()):
            props = props_by_id.get(node_id, {})
            if self._upsert_embedding(
                label=concept_label,
                node_id=node_id,
                props=props,
                embedding_field="embedding_graph",
                embedding=embeddings[node_id],
                model_name=graph_backend.model_name,
                model_version=graph_backend.model_name,
                content_hash=hash_graph_content(node_id=node_id, neighbours=sorted(neighbours_by_id.get(node_id, set()))),
                now=now,
            ):
                updated += 1
        return updated

    def _fetch_nodes(self, label: str) -> list[dict[str, Any]]:
        return self._client.run(f"MATCH (n:{label}) RETURN n.id AS id, properties(n) AS props")

    def _upsert_embedding(
        self,
        *,
        label: str,
        node_id: str,
        props: Mapping[str, Any],
        embedding_field: str,
        embedding: list[float],
        model_name: str,
        model_version: str,
        content_hash: str,
        now: datetime,
    ) -> bool:
        model_field = f"{embedding_field}_model"
        existing = props.get(embedding_field)
        hash_field = f"{embedding_field}_content_hash"
        existing_hash = props.get(hash_field) or props.get("content_hash")
        if existing is not None and existing_hash == content_hash:
            return False

        self._client.run(
            (
                f"MATCH (n:{label} {{id: $id}}) "
                f"SET n.{embedding_field} = $embedding, "
                "n.embedding_model = $embedding_model, "
                "n.embedding_model_version = $embedding_model_version, "
                "n.content_hash = $content_hash, "
                f"n.{hash_field} = $content_hash, "
                "n.embedding_updated_at = datetime($embedding_updated_at), "
                f"n.{model_field} = $embedding_model"
            ),
            {
                "id": node_id,
                "embedding": embedding,
                "embedding_model": model_name,
                "embedding_model_version": model_version,
                "content_hash": content_hash,
                "embedding_updated_at": _to_iso(now),
            },
        )
        return True


def _to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _hash_text_embedding(text: str, dimensions: int) -> list[float]:
    normalized = text.strip().lower().encode("utf-8")
    digest = hashlib.sha256(normalized).digest()
    values: list[float] = []
    for idx in range(dimensions):
        byte = digest[idx % len(digest)]
        values.append((byte / 127.5) - 1.0)
    norm = math.sqrt(sum(value * value for value in values)) or 1.0
    return [value / norm for value in values]


def _select_text_fields(props: Mapping[str, Any]) -> str:
    preferred = [
        "name",
        "title",
        "summary",
        "description",
        "text",
        "content",
        "kind",
        "type",
    ]
    parts: list[str] = []
    for key in preferred:
        value = props.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    if not parts:
        for key in sorted(props.keys()):
            value = props[key]
            if isinstance(value, str) and value.strip() and len(value) <= 280:
                parts.append(value.strip())
    return "\n".join(parts)


def _deterministic_graph_embedding(
    node_ids: list[str],
    edges: Iterable[tuple[str, str]],
    dimensions: int,
    seed: int,
) -> dict[str, list[float]]:
    adjacency: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    for src, dst in edges:
        if src not in adjacency:
            adjacency[src] = set()
        if dst not in adjacency:
            adjacency[dst] = set()
        adjacency[src].add(dst)
        adjacency[dst].add(src)

    vectors: dict[str, list[float]] = {}
    for node_id in sorted(adjacency.keys()):
        rng = random.Random(f"{seed}:{node_id}")
        vectors[node_id] = [rng.uniform(-1.0, 1.0) for _ in range(dimensions)]

    for _ in range(3):
        next_vectors: dict[str, list[float]] = {}
        for node_id in sorted(adjacency.keys()):
            base = vectors[node_id]
            neighbours = sorted(adjacency[node_id])
            if not neighbours:
                next_vectors[node_id] = _normalize(base)
                continue
            merged = [0.0] * dimensions
            for neighbour in neighbours:
                nvec = vectors[neighbour]
                for idx in range(dimensions):
                    merged[idx] += nvec[idx]
            scale = float(len(neighbours))
            averaged = [merged[idx] / scale for idx in range(dimensions)]
            blend = [(0.6 * base[idx]) + (0.4 * averaged[idx]) for idx in range(dimensions)]
            next_vectors[node_id] = _normalize(blend)
        vectors = next_vectors

    return {node_id: _normalize(vector) for node_id, vector in vectors.items()}


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


__all__ = [
    "TextEmbeddingBackend",
    "GraphEmbeddingBackend",
    "LocalSentenceEmbeddingBackend",
    "Node2VecGraphEmbeddingBackend",
    "EmbeddingService",
]
