from __future__ import annotations

import hashlib
import logging
import math
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Mapping, Sequence

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConceptAssignmentSettings:
    """Configurable scoring settings for concept assignment."""

    embedding_similarity_threshold: float = 0.2
    decision_threshold: float = 0.4
    ambiguity_gap: float = 0.1
    embedding_weight: float = 0.85
    structural_weight: float = 0.1
    lexical_weight: float = 0.05
    embedding_dimensions: int = 24

    @classmethod
    def from_thresholds(cls, thresholds: Mapping[str, Any] | None, category: str) -> "ConceptAssignmentSettings":
        data = thresholds or {}
        defaults = data.get("defaults", {}) if isinstance(data.get("defaults"), Mapping) else {}
        section = data.get(category, {}) if isinstance(data.get(category), Mapping) else {}

        def _pick(key: str, default: float) -> float:
            value = section.get(key, defaults.get(key, default))
            try:
                return float(value)
            except (TypeError, ValueError):
                return float(default)

        return cls(
            embedding_similarity_threshold=_pick("embedding_similarity_threshold", cls.embedding_similarity_threshold),
            decision_threshold=_pick("decision_threshold", cls.decision_threshold),
            ambiguity_gap=_pick("ambiguity_gap", cls.ambiguity_gap),
            embedding_weight=_pick("embedding_weight", cls.embedding_weight),
            structural_weight=_pick("structural_weight", cls.structural_weight),
            lexical_weight=_pick("lexical_weight", cls.lexical_weight),
        )


class ConceptAssignmentEngine:
    """Assign concepts by prioritising embedding similarity with structural compatibility."""

    def __init__(self, settings: ConceptAssignmentSettings | None = None) -> None:
        self.settings = settings or ConceptAssignmentSettings()

    def assign(
        self,
        *,
        concept_key: str,
        value: str,
        candidates: Sequence[Mapping[str, Any]],
        context: Mapping[str, Any] | None = None,
        value_embedding: Sequence[float] | None = None,
    ) -> dict[str, Any]:
        settings = self.settings
        context = context or {}
        source_embedding = self._as_embedding(value_embedding) or self._embed_text(value)
        logger.info(
            "Concept assignment threshold for %s: decision_threshold=%.3f, embedding_threshold=%.3f",
            concept_key,
            settings.decision_threshold,
            settings.embedding_similarity_threshold,
        )

        scored: list[dict[str, Any]] = []
        for entry in candidates:
            entry_embedding = self._entry_embedding(entry)
            cosine = _cosine_similarity(source_embedding, entry_embedding)
            structural = self._structural_compatibility(context, entry)
            lexical = self._lexical_similarity(value, entry)
            total = (
                (settings.embedding_weight * cosine)
                + (settings.structural_weight * structural)
                + (settings.lexical_weight * lexical)
            )
            scored.append(
                {
                    "id": entry.get("id"),
                    "name": entry.get("name"),
                    "score": float(total),
                    "cosine_similarity": float(cosine),
                    "structural_compatibility": float(structural),
                    "lexical_similarity": float(lexical),
                    "embedding_similarity": float(cosine),
                }
            )
            logger.debug(
                "Concept candidate %s => cosine=%.4f structural=%.4f lexical=%.4f total=%.4f",
                entry.get("id"),
                cosine,
                structural,
                lexical,
                total,
            )

        scored.sort(key=lambda item: item.get("score", 0.0), reverse=True)
        logger.info("Competing concept candidates for %r: %s", value, [self._compact(c) for c in scored[:5]])

        if not scored:
            return self._unmatched(value)

        best = scored[0]
        runner_up = scored[1] if len(scored) > 1 else None
        status = "matched"

        if best["embedding_similarity"] < settings.embedding_similarity_threshold:
            status = "unmatched"
        elif best["score"] < settings.decision_threshold:
            status = "unmatched"
        elif runner_up and (best["score"] - runner_up["score"] <= settings.ambiguity_gap):
            status = "ambiguous"

        decision_mode = "embedding_similarity" if best["embedding_similarity"] >= settings.embedding_similarity_threshold else "lexical_or_structural_fallback"
        logger.info(
            "execution_trace.concept_assignment_decision concept_key=%s source=%r canonical_id=%s status=%s mode=%s top_score=%.4f top_similarity=%.4f",
            concept_key,
            value,
            best.get("id"),
            status,
            decision_mode,
            float(best.get("score", 0.0)),
            float(best.get("embedding_similarity", 0.0)),
        )

        return {
            "source": value,
            "canonical_id": best.get("id") if status == "matched" else None,
            "name": best.get("name") if status == "matched" else None,
            "score": float(best.get("score", 0.0)),
            "status": status,
            "decision_threshold": settings.decision_threshold,
            "candidates": scored,
        }

    def _entry_embedding(self, entry: Mapping[str, Any]) -> list[float]:
        candidate_embedding = self._as_embedding(entry.get("embedding"))
        if candidate_embedding:
            return candidate_embedding

        alias_values = entry.get("aliases") if isinstance(entry.get("aliases"), Sequence) else []
        aliases = [str(alias) for alias in alias_values if isinstance(alias, str)]
        basis = "\n".join(
            part
            for part in [
                str(entry.get("id") or ""),
                str(entry.get("name") or ""),
                str(entry.get("description") or ""),
                " ".join(aliases),
            ]
            if part
        )
        return self._embed_text(basis)

    def _lexical_similarity(self, value: str, entry: Mapping[str, Any]) -> float:
        value_norm = _normalise_text(value) or ""
        entry_name = _normalise_text(entry.get("name")) or ""
        entry_id = _normalise_text(entry.get("id")) or ""
        aliases = entry.get("aliases") if isinstance(entry.get("aliases"), Sequence) else []
        alias_norm = {_normalise_text(alias) for alias in aliases if _normalise_text(alias)}

        if value_norm and (value_norm == entry_id or value_norm == entry_name or value_norm in alias_norm):
            return 1.0
        if not value_norm or not entry_name:
            return 0.0
        return SequenceMatcher(None, value_norm, entry_name).ratio()

    def _structural_compatibility(self, context: Mapping[str, Any], entry: Mapping[str, Any]) -> float:
        context_type = _normalise_text(context.get("entity_type") or context.get("node_type"))
        applies_to = entry.get("applies_to") if isinstance(entry.get("applies_to"), Sequence) else []
        allowed_types = {_normalise_text(item) for item in applies_to if _normalise_text(item)}
        if not allowed_types:
            return 0.5
        if not context_type:
            return 0.5
        return 1.0 if context_type in allowed_types else 0.0

    def _embed_text(self, text: str) -> list[float]:
        dims = max(8, self.settings.embedding_dimensions)
        vector = [0.0] * dims
        tokens = [token for token in text.strip().lower().split() if token]
        if not tokens:
            return vector
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            for idx in range(dims):
                byte = digest[idx % len(digest)]
                signed = (byte / 127.5) - 1.0
                vector[idx] += signed
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    def _as_embedding(self, value: Any) -> list[float] | None:
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
            return None
        parsed: list[float] = []
        for item in value:
            if isinstance(item, bool):
                return None
            if isinstance(item, (int, float)):
                parsed.append(float(item))
            else:
                return None
        if not parsed:
            return None
        norm = math.sqrt(sum(item * item for item in parsed)) or 1.0
        return [item / norm for item in parsed]

    def _compact(self, candidate: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "id": candidate.get("id"),
            "score": round(float(candidate.get("score", 0.0)), 4),
            "cosine_similarity": round(float(candidate.get("cosine_similarity", 0.0)), 4),
        }

    def _unmatched(self, value: str) -> dict[str, Any]:
        return {
            "source": value,
            "canonical_id": None,
            "name": None,
            "score": 0.0,
            "status": "unmatched",
            "decision_threshold": self.settings.decision_threshold,
            "candidates": [],
        }


def _normalise_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    return value.strip().lower() or None


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or not right:
        return 0.0
    length = min(len(left), len(right))
    if length == 0:
        return 0.0
    left_trim = left[:length]
    right_trim = right[:length]
    numerator = sum(a * b for a, b in zip(left_trim, right_trim, strict=False))
    left_norm = math.sqrt(sum(a * a for a in left_trim)) or 1.0
    right_norm = math.sqrt(sum(b * b for b in right_trim)) or 1.0
    return max(-1.0, min(1.0, numerator / (left_norm * right_norm)))


__all__ = ["ConceptAssignmentSettings", "ConceptAssignmentEngine"]
