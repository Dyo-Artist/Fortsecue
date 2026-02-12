from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence


def hash_text_content(text: str) -> str:
    """Return a stable sha256 hash for normalized text content."""
    normalized = "\n".join(line.rstrip() for line in text.strip().splitlines())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def hash_graph_content(*, node_id: str, neighbours: Sequence[str]) -> str:
    """Return a stable sha256 hash for graph neighbourhood content."""
    payload = {
        "node_id": str(node_id),
        "neighbours": sorted(str(neighbour) for neighbour in neighbours),
    }
    return _hash_payload(payload)


def hash_mapping_content(payload: Mapping[str, Any]) -> str:
    """Return a stable sha256 hash for mapping content."""
    return _hash_payload(payload)


def _hash_payload(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


__all__ = ["hash_text_content", "hash_graph_content", "hash_mapping_content"]
