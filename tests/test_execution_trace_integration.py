from __future__ import annotations

import pathlib
import re
import sys
from typing import Any

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from logos import main
from logos.api.routes import ingest as ingest_routes
from logos.core import pipeline_executor


_LABEL_RE = re.compile(r"\(n:([A-Za-z0-9_]+)")


class FakeTx:
    def __init__(self, graph: "FakeGraphClient") -> None:
        self.graph = graph

    def run(self, cypher: str, params: dict[str, Any] | None = None):
        return self.graph.run(cypher, params)


class FakeGraphClient:
    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, dict[str, Any]]] = {}
        self.relationships: list[tuple[str, dict[str, Any]]] = []

    def run_in_tx(self, fn) -> None:
        fn(FakeTx(self))

    def run(self, cypher: str, params: dict[str, Any] | None = None):
        params = params or {}

        if "MERGE (n:" in cypher and "SET n += $props" in cypher:
            label = _extract_label(cypher)
            node_id = str(params.get("id") or "")
            if label and node_id:
                props = dict(params.get("props") or {})
                props.setdefault("id", node_id)
                self.nodes.setdefault(label, {}).setdefault(node_id, {}).update(props)
            return []

        if "MATCH (n:" in cypher and "RETURN n.id AS id, properties(n) AS props" in cypher:
            label = _extract_label(cypher)
            if not label:
                return []
            return [
                {"id": node_id, "props": dict(props)}
                for node_id, props in sorted(self.nodes.get(label, {}).items())
            ]

        if "MATCH (n:" in cypher and "AS embedding" in cypher and "RETURN n.id AS id" in cypher:
            label = _extract_label(cypher)
            field_match = re.search(r"n\.([A-Za-z0-9_]+) AS embedding", cypher)
            field = field_match.group(1) if field_match else None
            rows: list[dict[str, Any]] = []
            if label and field:
                for node_id, props in sorted(self.nodes.get(label, {}).items()):
                    if field in props:
                        rows.append({"id": node_id, "embedding": props[field]})
            return rows

        if "MATCH (n:" in cypher and "SET n.embedding_" in cypher:
            label = _extract_label(cypher)
            node_id = str(params.get("id") or "")
            if label and node_id:
                node = self.nodes.setdefault(label, {}).setdefault(node_id, {"id": node_id})
                for key, value in params.items():
                    if key in {"embedding", "embedding_model", "embedding_model_version", "content_hash", "embedding_updated_at"}:
                        continue
                if "embedding_text" in cypher:
                    node["embedding_text"] = list(params.get("embedding") or [])
                if "embedding_graph" in cypher:
                    node["embedding_graph"] = list(params.get("embedding") or [])
                node["embedding_model"] = params.get("embedding_model")
            return []

        if "MERGE (c:" in cypher or "MERGE (e)-[r:" in cypher:
            self.relationships.append((cypher, dict(params)))
            return []

        return []


def _extract_label(cypher: str) -> str | None:
    match = _LABEL_RE.search(cypher)
    return match.group(1) if match else None


def test_ingest_commit_persists_embeddings_and_assignment_evidence(monkeypatch) -> None:
    fake_graph = FakeGraphClient()
    monkeypatch.setattr(ingest_routes, "get_client", lambda: fake_graph)
    monkeypatch.setattr(pipeline_executor.OntologyIntegrityGuard, "validate", lambda self, bundle, context=None: None)

    client = TestClient(main.app)

    ingest_response = client.post(
        "/api/v1/ingest/text",
        json={"text": "Jordan shared a governance update with the city council."},
    )
    assert ingest_response.status_code == 200
    payload = ingest_response.json()

    preview = payload["preview"]
    preview.setdefault("entities", {})
    preview["entities"].setdefault("persons", [])
    if not preview["entities"]["persons"]:
        preview["entities"]["persons"].append({"id": "person_trace_1", "name": "Jordan"})
    person = preview["entities"]["persons"][0]
    person["hints"] = {"stakeholder_type": "novel oversight counterpart"}
    person["embedding"] = [
        0.2339694677804886,
        -0.17953361845348462,
        0.2957332199015125,
        -0.006804481165875514,
        0.30620165246439784,
        -0.08427088213122744,
        -0.06228717374916809,
        -0.17639308868461895,
        0.24234421383079693,
        -0.07484929282463058,
        -0.0915987849252473,
        0.2925926901326469,
        -0.12405092587019194,
        0.2318757812679116,
        0.11148880679472947,
        -0.044490838392262914,
        -0.34179432317820824,
        0.16906518589059918,
        0.10730143376957534,
        -0.4527597083447935,
        -0.1680183426343106,
        0.0926456281815358,
        -0.20256417009183245,
        0.08950509841267014,
    ]



    commit_response = client.post(
        f"/api/v1/interactions/{payload['interaction_id']}/commit",
        json=preview,
    )
    assert commit_response.status_code == 200

    person_node = next(iter(fake_graph.nodes.get("Person", {}).values()))
    assert person_node.get("embedding_text")

    assignment = person_node.get("hint_resolution", {}).get("stakeholder_types")
    assert assignment
    assert assignment["canonical_id"] == "st_community_rep"
    assert assignment["status"] == "matched"
    top_candidate = assignment["candidates"][0]
    assert top_candidate["embedding_similarity"] >= assignment["decision_threshold"]
    assert top_candidate["lexical_similarity"] < top_candidate["embedding_similarity"]
