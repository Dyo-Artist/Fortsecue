from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from logos.graphio.neo4j_client import Neo4jClient, get_client
from logos.graphio.schema_store import SchemaStore


@dataclass(frozen=True)
class ClusterMember:
    entity_id: str
    entity_label: str
    score: float


@dataclass(frozen=True)
class ClusterHypothesis:
    cluster_id: str
    kind: str
    algorithm: str
    members: tuple[ClusterMember, ...]
    provenance: Mapping[str, Any]


class ClusteringService:
    """Generate graph cluster hypotheses from embedding spaces and persist to Neo4j."""

    def __init__(
        self,
        *,
        client: Neo4jClient | None = None,
        schema_store: SchemaStore | None = None,
    ) -> None:
        self._client = client or get_client()
        self._schema_store = schema_store or SchemaStore(mutable=True)

    def run(
        self,
        *,
        run_hdbscan: bool = True,
        run_leiden: bool = True,
        updated_at: datetime | None = None,
    ) -> dict[str, int]:
        now = updated_at or datetime.now(timezone.utc)
        created_at = _to_iso(now)

        cluster_label = self._schema_store.get_schema_convention("concept_cluster_label", "ConceptCluster") or "ConceptCluster"
        in_cluster_rel = self._schema_store.get_schema_convention("in_cluster_relationship", "IN_CLUSTER") or "IN_CLUSTER"
        concept_label = self._schema_store.get_schema_convention("concept_label", "Concept") or "Concept"
        particular_label = self._schema_store.get_schema_convention("particular_label", "Particular") or "Particular"
        interaction_label = self._schema_store.get_schema_convention("interaction_label", "Interaction") or "Interaction"

        hypotheses: list[ClusterHypothesis] = []
        if run_hdbscan:
            hypotheses.extend(
                self._build_hdbscan_hypotheses(
                    particular_label=particular_label,
                    interaction_label=interaction_label,
                    created_at=created_at,
                )
            )
        if run_leiden:
            hypotheses.extend(
                self._build_leiden_hypotheses(
                    concept_label=concept_label,
                    created_at=created_at,
                )
            )

        for hypothesis in hypotheses:
            self._write_cluster_hypothesis(
                cluster_label=cluster_label,
                in_cluster_rel=in_cluster_rel,
                hypothesis=hypothesis,
                created_at=created_at,
            )

        self._schema_store.record_node_type(
            cluster_label,
            {"id", "kind", "created_at", "algorithm", "status", "provenance", "updated_at"},
            concept_kind="ClusterHypothesis",
            now=now,
        )
        self._schema_store.record_relationship_type(
            in_cluster_rel,
            {"score", "algorithm", "created_at", "provenance"},
            now=now,
        )

        return {
            "clusters_created": len(hypotheses),
            "memberships_created": sum(len(cluster.members) for cluster in hypotheses),
        }

    def _build_hdbscan_hypotheses(
        self,
        *,
        particular_label: str,
        interaction_label: str,
        created_at: str,
    ) -> list[ClusterHypothesis]:
        rows = self._fetch_embedding_rows(particular_label, "embedding_text")
        rows.extend(self._fetch_embedding_rows(interaction_label, "embedding_text"))
        if len(rows) < 2:
            return []

        item_ids = [row["id"] for row in rows]
        vectors = [row["embedding"] for row in rows]
        labels, probabilities = _hdbscan_labels(vectors)

        grouped: dict[int, list[ClusterMember]] = defaultdict(list)
        for idx, label in enumerate(labels):
            if label < 0:
                continue
            grouped[int(label)].append(
                ClusterMember(
                    entity_id=item_ids[idx],
                    entity_label=rows[idx]["label"],
                    score=float(probabilities[idx]),
                )
            )

        hypotheses: list[ClusterHypothesis] = []
        for group_id, members in sorted(grouped.items()):
            if len(members) < 2:
                continue
            kind = "embedding_hypothesis_text"
            cluster_id = _cluster_id(kind=kind, algorithm="hdbscan", seed=f"{group_id}:{created_at}", members=members)
            hypotheses.append(
                ClusterHypothesis(
                    cluster_id=cluster_id,
                    kind=kind,
                    algorithm="hdbscan",
                    members=tuple(sorted(members, key=lambda m: (m.entity_label, m.entity_id))),
                    provenance={
                        "status": "hypothesis",
                        "sources": [particular_label, interaction_label],
                        "embedding_field": "embedding_text",
                        "review_required": True,
                    },
                )
            )
        return hypotheses

    def _build_leiden_hypotheses(self, *, concept_label: str, created_at: str) -> list[ClusterHypothesis]:
        rows = self._fetch_embedding_rows(concept_label, "embedding_graph")
        if len(rows) < 3:
            return []

        ids = [row["id"] for row in rows]
        vectors = [row["embedding"] for row in rows]
        edges, similarities = _build_knn_neighbourhood(ids, vectors, k=min(5, max(2, len(ids) - 1)))
        communities = _leiden_communities(ids, edges)

        hypotheses: list[ClusterHypothesis] = []
        for community_index, member_ids in enumerate(sorted(communities, key=lambda g: (len(g), g))):
            if len(member_ids) < 2:
                continue
            member_scores = _community_scores(member_ids, similarities)
            members = [
                ClusterMember(entity_id=node_id, entity_label=concept_label, score=member_scores.get(node_id, 0.0))
                for node_id in sorted(member_ids)
            ]
            kind = "embedding_hypothesis_graph"
            cluster_id = _cluster_id(kind=kind, algorithm="leiden", seed=f"{community_index}:{created_at}", members=members)
            hypotheses.append(
                ClusterHypothesis(
                    cluster_id=cluster_id,
                    kind=kind,
                    algorithm="leiden",
                    members=tuple(members),
                    provenance={
                        "status": "hypothesis",
                        "sources": [concept_label],
                        "embedding_field": "embedding_graph",
                        "graph": "knn_neighbourhood",
                        "review_required": True,
                    },
                )
            )
        return hypotheses

    def _fetch_embedding_rows(self, label: str, embedding_field: str) -> list[dict[str, Any]]:
        rows = self._client.run(
            f"MATCH (n:{label}) "
            f"WHERE n.id IS NOT NULL AND n.{embedding_field} IS NOT NULL "
            f"RETURN n.id AS id, n.{embedding_field} AS embedding"
        )
        payload: list[dict[str, Any]] = []
        for row in rows:
            node_id = str(row.get("id") or "").strip()
            embedding_raw = row.get("embedding")
            if not node_id or not isinstance(embedding_raw, Sequence):
                continue
            try:
                embedding = [float(value) for value in embedding_raw]
            except (TypeError, ValueError):
                continue
            payload.append({"id": node_id, "label": label, "embedding": embedding})
        payload.sort(key=lambda item: item["id"])
        return payload

    def _write_cluster_hypothesis(
        self,
        *,
        cluster_label: str,
        in_cluster_rel: str,
        hypothesis: ClusterHypothesis,
        created_at: str,
    ) -> None:
        self._client.run(
            (
                f"MERGE (c:{cluster_label} {{id: $id}}) "
                "ON CREATE SET c.created_at = datetime($created_at) "
                "SET c.kind = $kind, c.algorithm = $algorithm, c.status = 'hypothesis', "
                "c.provenance = $provenance, c.updated_at = datetime($created_at)"
            ),
            {
                "id": hypothesis.cluster_id,
                "kind": hypothesis.kind,
                "algorithm": hypothesis.algorithm,
                "created_at": created_at,
                "provenance": dict(hypothesis.provenance),
            },
        )

        for member in hypothesis.members:
            self._client.run(
                (
                    f"MATCH (e:{member.entity_label} {{id: $entity_id}}) "
                    f"MATCH (c:{cluster_label} {{id: $cluster_id}}) "
                    f"MERGE (e)-[r:{in_cluster_rel}]->(c) "
                    "SET r.score = $score, r.algorithm = $algorithm, "
                    "r.created_at = datetime($created_at), r.provenance = $provenance"
                ),
                {
                    "entity_id": member.entity_id,
                    "cluster_id": hypothesis.cluster_id,
                    "score": float(member.score),
                    "algorithm": hypothesis.algorithm,
                    "created_at": created_at,
                    "provenance": dict(hypothesis.provenance),
                },
            )


def _hdbscan_labels(vectors: list[list[float]]) -> tuple[list[int], list[float]]:
    if len(vectors) < 2:
        return [], []
    try:
        import hdbscan  # type: ignore

        clusterer = hdbscan.HDBSCAN(min_cluster_size=max(2, min(5, len(vectors) // 2)), metric="euclidean")
        labels = [int(label) for label in clusterer.fit_predict(vectors)]
        probabilities = [float(p) for p in getattr(clusterer, "probabilities_", [1.0] * len(labels))]
        if len(probabilities) != len(labels):
            probabilities = [1.0] * len(labels)
        return labels, probabilities
    except Exception:
        # Fallback: one deterministic cluster with confidence from centroid similarity.
        centroid = [sum(vector[idx] for vector in vectors) / float(len(vectors)) for idx in range(len(vectors[0]))]
        probabilities = [_cosine_similarity(vector, centroid) for vector in vectors]
        return [0] * len(vectors), probabilities


def _build_knn_neighbourhood(
    ids: list[str],
    vectors: list[list[float]],
    *,
    k: int,
) -> tuple[set[tuple[str, str]], dict[tuple[str, str], float]]:
    edges: set[tuple[str, str]] = set()
    similarities: dict[tuple[str, str], float] = {}
    for idx, src in enumerate(ids):
        scored: list[tuple[float, str]] = []
        for jdx, dst in enumerate(ids):
            if idx == jdx:
                continue
            similarity = _cosine_similarity(vectors[idx], vectors[jdx])
            scored.append((similarity, dst))
            key = tuple(sorted((src, dst)))
            similarities[key] = similarity
        scored.sort(reverse=True)
        for _, dst in scored[:k]:
            edges.add(tuple(sorted((src, dst))))
    return edges, similarities


def _leiden_communities(ids: list[str], edges: set[tuple[str, str]]) -> list[set[str]]:
    if not ids:
        return []
    try:
        import igraph as ig  # type: ignore
        import leidenalg  # type: ignore

        graph = ig.Graph()
        graph.add_vertices(ids)
        graph.add_edges(list(edges))
        partition = leidenalg.find_partition(graph, leidenalg.ModularityVertexPartition)
        communities: list[set[str]] = []
        for group in partition:
            communities.append({ids[index] for index in group})
        return communities
    except Exception:
        adjacency: dict[str, set[str]] = {node_id: set() for node_id in ids}
        for src, dst in edges:
            adjacency[src].add(dst)
            adjacency[dst].add(src)
        visited: set[str] = set()
        communities: list[set[str]] = []
        for node_id in ids:
            if node_id in visited:
                continue
            stack = [node_id]
            component: set[str] = set()
            while stack:
                current = stack.pop()
                if current in visited:
                    continue
                visited.add(current)
                component.add(current)
                stack.extend(sorted(adjacency[current] - visited))
            communities.append(component)
        return communities


def _community_scores(member_ids: set[str], similarities: Mapping[tuple[str, str], float]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for member_id in member_ids:
        peers = [other for other in member_ids if other != member_id]
        if not peers:
            scores[member_id] = 1.0
            continue
        values = [similarities.get(tuple(sorted((member_id, peer))), 0.0) for peer in peers]
        score = (sum(values) / float(len(values)) + 1.0) / 2.0
        scores[member_id] = max(0.0, min(1.0, score))
    return scores


def _cluster_id(*, kind: str, algorithm: str, seed: str, members: Sequence[ClusterMember]) -> str:
    joined = "|".join(f"{member.entity_label}:{member.entity_id}" for member in sorted(members, key=lambda m: (m.entity_label, m.entity_id)))
    digest = hashlib.sha1(f"{kind}:{algorithm}:{seed}:{joined}".encode("utf-8")).hexdigest()[:16]
    return f"cluster_{digest}"


def _cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    numerator = sum(float(x) * float(y) for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(float(x) * float(x) for x in a)) or 1.0
    norm_b = math.sqrt(sum(float(y) * float(y) for y in b)) or 1.0
    return numerator / (norm_a * norm_b)


def _to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


__all__ = ["ClusteringService", "ClusterHypothesis", "ClusterMember"]
