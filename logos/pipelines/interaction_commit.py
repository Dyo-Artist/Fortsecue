from __future__ import annotations

import json
import logging
from collections import Counter, deque
from pathlib import Path
from statistics import mean
from typing import Any, Dict, Iterable, Mapping

import yaml

from logos.core.pipeline_executor import PipelineContext, STAGE_REGISTRY
from logos.feedback.store import DEFAULT_FEEDBACK_DIR
from logos.knowledgebase.store import KnowledgebaseStore
from logos.models.bundles import FeedbackBundle

logger = logging.getLogger(__name__)


def _trace(context: Dict[str, Any], stage_name: str) -> None:
    trace: list[str] = context.setdefault("trace", [])  # type: ignore[assignment]
    trace.append(stage_name)


def _load_recent_feedback(path: Path, limit: int) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    entries: deque[dict[str, Any]] = deque(maxlen=max(limit, 1))
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("feedback_parse_failed", extra={"line_preview": line[:80]})
                continue
            if isinstance(payload, Mapping):
                entries.append(dict(payload))
    return list(entries)


def _entry_from_feedback_bundle(bundle: FeedbackBundle) -> dict[str, Any]:
    payload = bundle.model_dump(mode="json", exclude_none=True)
    entry = {
        "interaction_id": bundle.meta.interaction_id,
        "user_id": bundle.user_id,
        "feedback": bundle.feedback,
        "rating": bundle.rating,
        "corrections": bundle.corrections,
    }
    if "timestamp" in payload:
        entry["timestamp"] = payload["timestamp"]
    return entry


def _iter_corrections(entries: Iterable[Mapping[str, Any]]) -> Iterable[dict[str, Any]]:
    for entry in entries:
        corrections = entry.get("corrections")
        if isinstance(corrections, list):
            for correction in corrections:
                if isinstance(correction, Mapping):
                    yield dict(correction)


def _path_has_keywords(path: str, keywords: Iterable[str]) -> bool:
    lowered = path.lower()
    return any(keyword in lowered for keyword in keywords)


def _string_value(value: Any) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _numeric_value(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _load_threshold_defaults(kb_store: KnowledgebaseStore) -> dict[str, float]:
    path = kb_store.base_path / "rules" / "merge_thresholds.yml"
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    defaults = payload.get("defaults") if isinstance(payload, Mapping) else None
    if not isinstance(defaults, Mapping):
        return {}
    parsed: dict[str, float] = {}
    for key, value in defaults.items():
        if isinstance(value, (int, float)):
            parsed[str(key)] = float(value)
    return parsed


@STAGE_REGISTRY.register("S7_REFLECT_AND_LEARN")
def stage_reflect_and_learn(bundle: Any, ctx: PipelineContext) -> Any:
    context = ctx.to_mapping()
    _trace(context, "S7_REFLECT_AND_LEARN")

    limit = int(context.get("feedback_recent_limit", 50) or 50)
    threshold = int(context.get("feedback_recurring_threshold", 2) or 2)
    feedback_dir = Path(context.get("feedback_dir") or DEFAULT_FEEDBACK_DIR)
    feedback_path = feedback_dir / "feedback.jsonl"

    entries = _load_recent_feedback(feedback_path, limit)
    feedback_payload = context.get("feedback_bundle")
    if isinstance(feedback_payload, FeedbackBundle):
        entries.append(_entry_from_feedback_bundle(feedback_payload))
    elif isinstance(feedback_payload, Mapping):
        feedback_bundle = FeedbackBundle.model_validate(feedback_payload)
        entries.append(_entry_from_feedback_bundle(feedback_bundle))

    if len(entries) > limit:
        entries = entries[-limit:]
    if not entries:
        logger.info("reflect_and_learn_no_feedback", extra={"stage": "S7_REFLECT_AND_LEARN"})
        return bundle

    actor = str(context.get("user") or context.get("user_id") or "system")
    knowledgebase_path = context.get("knowledgebase_path")
    if not knowledgebase_path:
        logger.info("reflect_and_learn_skip_no_kb", extra={"stage": "S7_REFLECT_AND_LEARN"})
        return bundle
    kb_store = KnowledgebaseStore(base_path=knowledgebase_path, actor=actor)

    obligation_candidates: Counter[str] = Counter()
    synonym_candidates: Counter[tuple[str, str, str]] = Counter()
    correction_counts: Counter[str] = Counter()
    confidence_deltas: list[float] = []
    concept_candidates: list[dict[str, Any]] = []
    review_items: list[dict[str, Any]] = []

    for correction in _iter_corrections(entries):
        path = str(correction.get("path") or "")
        before = correction.get("before")
        after = correction.get("after")
        correction_counts[path] += 1

        before_text = _string_value(before)
        after_text = _string_value(after)

        if after_text and _path_has_keywords(path, ["commitment", "obligation", "due_date", "deadline"]):
            obligation_candidates[after_text] += 1
        if before_text and after_text and _path_has_keywords(path, ["name", "label", "title", "summary"]):
            if before_text != after_text:
                synonym_candidates[(before_text, after_text, path)] += 1

        if _path_has_keywords(path, ["confidence", "similarity", "score"]):
            before_num = _numeric_value(before)
            after_num = _numeric_value(after)
            if before_num is not None and after_num is not None:
                confidence_deltas.append(after_num - before_num)

        if _path_has_keywords(path, ["concept", "topic", "type"]):
            if after_text:
                concept_candidates.append({"path": path, "value": after_text})
            elif isinstance(after, Mapping):
                concept_candidates.append({"path": path, "value": dict(after)})

        if not after_text and not isinstance(after, (int, float, Mapping, list)):
            review_items.append({"path": path, "before": before, "after": after})

    updates: dict[str, list[str]] = {
        "lexicon_updates": [],
        "synonym_updates": [],
        "threshold_updates": [],
        "concept_promotions": [],
        "review_items": [],
    }
    deltas: dict[str, Any] = {
        "correction_count_by_path": dict(correction_counts),
        "confidence_delta_count": len(confidence_deltas),
    }

    for phrase, count in obligation_candidates.items():
        if count >= threshold:
            added = kb_store.add_obligation_phrase(phrase, reason="Feedback-driven obligation pattern")
            if added:
                updates["lexicon_updates"].append(phrase)
                logger.info("reflect_obligation_added", extra={"phrase": phrase, "count": count})

    for (before_text, after_text, path), count in synonym_candidates.items():
        if count >= threshold:
            added = kb_store.add_lexicon_entry(
                lexicon_name="synonyms.yml",
                entry={"from": before_text, "to": after_text, "context": path},
                list_key="pairs",
                unique_fields=["from", "to", "context"],
                reason="Feedback-driven synonym pair",
            )
            if added:
                updates["synonym_updates"].append(f"{before_text} -> {after_text}")
                logger.info(
                    "reflect_synonym_added",
                    extra={"before": before_text, "after": after_text, "path": path, "count": count},
                )

    if confidence_deltas and len(confidence_deltas) >= threshold:
        avg_delta = mean(confidence_deltas)
        defaults_before = _load_threshold_defaults(kb_store)
        if defaults_before:
            delta = 0.01 if avg_delta < 0 else -0.01
            adjustments = {key: delta for key in defaults_before.keys()}
            applied = kb_store.update_merge_thresholds(
                adjustments,
                scope="defaults",
                reason="Feedback-driven confidence adjustment",
            )
            defaults_after = _load_threshold_defaults(kb_store)
            deltas["threshold_defaults"] = {
                key: {"before": defaults_before.get(key), "after": defaults_after.get(key)}
                for key in defaults_before.keys()
            }
            for key, value in applied.items():
                updates["threshold_updates"].append(f"{key}={value:.2f}")
            if applied:
                logger.info(
                    "reflect_thresholds_adjusted",
                    extra={"delta": delta, "applied": applied, "avg_delta": avg_delta},
                )

    for candidate in concept_candidates:
        if kb_store.record_learning_signal(
            "concept_promotion_candidate",
            candidate,
            status="pending",
            reason="Feedback-driven concept promotion candidate",
        ):
            updates["concept_promotions"].append(str(candidate.get("value")))
            logger.info("reflect_concept_promotion_logged", extra={"candidate": candidate})

    for item in review_items:
        if kb_store.record_learning_signal(
            "feedback_review",
            item,
            status="needs_review",
            reason="Feedback item requires human review",
        ):
            updates["review_items"].append(str(item.get("path")))
            logger.info("reflect_review_logged", extra={"item": item})

    context["learning_updates"] = updates
    context["learning_deltas"] = deltas
    logger.info("reflect_and_learn_delta", extra={"deltas": deltas, "stage": "S7_REFLECT_AND_LEARN"})
    logger.info(
        "reflect_and_learn_completed",
        extra={"updates": updates, "total_feedback": len(entries)},
    )
    return bundle


__all__ = ["stage_reflect_and_learn"]
