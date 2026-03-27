from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import yaml

from .models import (
    BeliefPointer,
    ContradictionDetectionResult,
    ContradictionRecord,
    ContradictionRules,
    PredicateConstraint,
    TemporalRule,
)

DEFAULT_RULES_PATH = Path(__file__).resolve().parents[1] / "knowledgebase" / "rules" / "contradictions.yml"


class ContradictionEngine:
    """Detect hard/soft/paradoxical contradictions from beliefs + KB constraints."""

    def __init__(self, rules: ContradictionRules | Mapping[str, Any] | None = None) -> None:
        if isinstance(rules, ContradictionRules):
            self._rules = rules
        elif isinstance(rules, Mapping):
            self._rules = ContradictionRules.model_validate(rules)
        else:
            self._rules = load_contradiction_rules()

    def detect(
        self,
        *,
        new_beliefs: list[Mapping[str, Any]] | None,
        existing_beliefs: list[Mapping[str, Any]] | None,
    ) -> ContradictionDetectionResult:
        if not new_beliefs:
            return ContradictionDetectionResult()

        existing_by_key: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
        for belief in existing_beliefs or []:
            key = self._subject_predicate_key(belief)
            if key is None:
                continue
            existing_by_key.setdefault(key, []).append(belief)

        contradictions: list[ContradictionRecord] = []

        for new_belief in new_beliefs:
            key = self._subject_predicate_key(new_belief)
            if key is None:
                continue

            for existing in existing_by_key.get(key, []):
                if self._belief_id(new_belief) == self._belief_id(existing):
                    continue
                contradiction = self._compare_pair(new_belief, existing)
                if contradiction:
                    contradictions.append(contradiction)

        return ContradictionDetectionResult(contradictions=contradictions)

    def _compare_pair(self, new_belief: Mapping[str, Any], existing: Mapping[str, Any]) -> ContradictionRecord | None:
        predicate = self._predicate(new_belief)
        if not predicate:
            return None

        hard = self._constraint_for(predicate, self._rules.hard_constraints)
        soft = self._constraint_for(predicate, self._rules.soft_constraints)
        temporal_rule = self._temporal_rule_for(predicate)

        new_object = self._object_ref(new_belief)
        existing_object = self._object_ref(existing)

        code = "value_disagreement"
        ctype = "soft"
        resolution = "Review evidence and optionally retain both beliefs with scoped context."
        explanation = f"Beliefs disagree on object for {predicate}."

        if temporal_rule and self._temporal_overlap_conflict(new_belief, existing, temporal_rule):
            code = temporal_rule.conflict_code
            ctype = "hard"
            resolution = temporal_rule.recommended_resolution
            explanation = f"Beliefs overlap in conflicting temporal windows for {predicate}."
        elif hard and hard.cardinality == 1 and new_object and existing_object and new_object != existing_object:
            code = hard.conflict_code or "cardinality_conflict"
            ctype = "hard"
            resolution = hard.recommended_resolution
            explanation = f"Predicate {predicate} enforces cardinality=1 but competing objects were asserted."
        elif self._type_mismatch(new_belief, existing):
            code = "type_mismatch"
            ctype = "soft"
            explanation = f"Beliefs use incompatible object typing for {predicate}."
        elif new_object and existing_object and new_object != existing_object:
            if soft:
                code = soft.conflict_code or "value_disagreement"
                ctype = "soft"
                resolution = soft.recommended_resolution
                explanation = f"Predicate {predicate} allows multiple values; mismatch kept as soft tension."
            else:
                return None
        else:
            return None

        if self._is_paradox_allowlisted(new_belief, existing):
            ctype = "paradoxical"
            resolution = "Paradox allowlisted by knowledgebase policy; preserve both assertions."

        return ContradictionRecord(
            type=ctype,
            code=code,
            explanation=explanation,
            recommended_resolution=resolution,
            involved_beliefs=[self._belief_pointer(new_belief), self._belief_pointer(existing)],
            metadata={"predicate": predicate},
        )

    def _belief_pointer(self, belief: Mapping[str, Any]) -> BeliefPointer:
        return BeliefPointer(
            belief_id=self._belief_id(belief) or "",
            subject_ref=self._subject_ref(belief),
            predicate=self._predicate(belief),
            object_ref=self._object_ref(belief),
        )

    @staticmethod
    def _constraint_for(predicate: str, constraints: list[PredicateConstraint]) -> PredicateConstraint | None:
        for constraint in constraints:
            if constraint.predicate == predicate:
                return constraint
        return None

    def _temporal_rule_for(self, predicate: str) -> TemporalRule | None:
        for rule in self._rules.temporal_rules:
            if rule.predicate == predicate:
                return rule
        return None

    @staticmethod
    def _statement(belief: Mapping[str, Any]) -> Mapping[str, Any]:
        statement = belief.get("statement")
        if isinstance(statement, str):
            try:
                parsed = json.loads(statement)
                if isinstance(parsed, Mapping):
                    return parsed
            except json.JSONDecodeError:
                return {}
        return statement if isinstance(statement, Mapping) else {}

    def _subject_predicate_key(self, belief: Mapping[str, Any]) -> tuple[str, str] | None:
        subject_ref = self._subject_ref(belief)
        predicate = self._predicate(belief)
        if not subject_ref or not predicate:
            return None
        return (subject_ref, predicate)

    def _belief_id(self, belief: Mapping[str, Any]) -> str | None:
        belief_id = belief.get("id")
        return belief_id if isinstance(belief_id, str) and belief_id else None

    def _subject_ref(self, belief: Mapping[str, Any]) -> str | None:
        if isinstance(belief.get("subject_ref"), str):
            return str(belief["subject_ref"])
        statement = self._statement(belief)
        subject = statement.get("subject") if isinstance(statement.get("subject"), Mapping) else {}
        ref = subject.get("ref")
        return str(ref) if isinstance(ref, str) and ref else None

    def _predicate(self, belief: Mapping[str, Any]) -> str | None:
        if isinstance(belief.get("predicate"), str) and belief.get("predicate"):
            return str(belief["predicate"])
        statement = self._statement(belief)
        predicate = statement.get("predicate")
        return str(predicate) if isinstance(predicate, str) and predicate else None

    def _object_ref(self, belief: Mapping[str, Any]) -> str | None:
        if isinstance(belief.get("object_ref"), str):
            return str(belief["object_ref"])
        statement = self._statement(belief)
        obj = statement.get("object") if isinstance(statement.get("object"), Mapping) else {}
        ref = obj.get("ref")
        if isinstance(ref, str) and ref:
            return ref
        value = obj.get("value")
        return str(value) if isinstance(value, (str, int, float)) else None

    def _type_mismatch(self, left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
        l_type = self._object_type(left)
        r_type = self._object_type(right)
        return bool(l_type and r_type and l_type != r_type)

    def _object_type(self, belief: Mapping[str, Any]) -> str | None:
        statement = self._statement(belief)
        obj = statement.get("object") if isinstance(statement.get("object"), Mapping) else {}
        label = obj.get("label") or obj.get("type")
        return str(label) if isinstance(label, str) and label else None

    def _is_paradox_allowlisted(self, left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
        predicate = self._predicate(left)
        if not predicate:
            return False
        left_subject = self._subject_ref(left)

        for entry in self._rules.paradox_allowlist:
            p = entry.get("predicate") if isinstance(entry, Mapping) else None
            if p and p != predicate:
                continue
            subject_ref = entry.get("subject_ref") if isinstance(entry, Mapping) else None
            if subject_ref and subject_ref != left_subject:
                continue
            return True
        return False

    @staticmethod
    def _parse_dt(value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None

    def _temporal_overlap_conflict(
        self, left: Mapping[str, Any], right: Mapping[str, Any], rule: TemporalRule
    ) -> bool:
        if not rule.overlap_conflict:
            return False

        left_start, left_end = self._time_window(left, rule)
        right_start, right_end = self._time_window(right, rule)
        if not left_start or not left_end or not right_start or not right_end:
            return False

        return left_start <= right_end and right_start <= left_end and self._object_ref(left) != self._object_ref(right)

    def _time_window(self, belief: Mapping[str, Any], rule: TemporalRule) -> tuple[datetime | None, datetime | None]:
        metadata = belief.get("metadata") if isinstance(belief.get("metadata"), Mapping) else {}
        statement = self._statement(belief)
        s_meta = statement.get("metadata") if isinstance(statement.get("metadata"), Mapping) else {}

        start_val = metadata.get(rule.start_key, s_meta.get(rule.start_key))
        end_val = metadata.get(rule.end_key, s_meta.get(rule.end_key))
        return self._parse_dt(start_val), self._parse_dt(end_val)


def load_contradiction_rules(path: str | Path | None = None) -> ContradictionRules:
    rules_path = Path(path) if path else DEFAULT_RULES_PATH
    if not rules_path.exists():
        return ContradictionRules()

    with rules_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    return ContradictionRules.model_validate(raw)
