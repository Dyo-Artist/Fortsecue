from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Sequence, Tuple
from uuid import uuid4

import yaml


MEMORY_RULES_PATH = Path(__file__).resolve().parent / "knowledgebase" / "rules" / "memory.yml"


class MemoryConfigError(RuntimeError):
    """Raised when the memory rules are missing or malformed."""


@dataclass
class MemoryItem:
    """Represents a unit of memory tracked by the memory manager."""

    id: str
    key: str
    content: Any
    created_at: datetime
    last_used: datetime
    importance: float = 0.0
    strength: float = 0.0
    ttl_seconds: int | None = None
    pinned: bool = False
    tags: Tuple[str, ...] = field(default_factory=tuple)
    scope: str = "short_term"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_expired(self, now: datetime) -> bool:
        if self.pinned:
            return False
        if self.ttl_seconds is None:
            return False
        return self.last_used + timedelta(seconds=self.ttl_seconds) < now

    def reinforce(self, amount: float, now: datetime, ttl_seconds: int | None) -> None:
        self.strength += amount
        self.last_used = now
        if ttl_seconds is not None:
            self.ttl_seconds = ttl_seconds


def load_memory_rules(path: Path | None = None) -> Dict[str, Any]:
    """Load memory tier rules from the knowledgebase configuration."""

    target = path or MEMORY_RULES_PATH
    if not target.exists():
        raise MemoryConfigError(f"Memory rules not found at {target}")

    try:
        with target.open("r", encoding="utf-8") as file:
            data = yaml.safe_load(file) or {}
    except yaml.YAMLError as exc:  # pragma: no cover - defensive YAML guard
        raise MemoryConfigError("Failed to parse memory rules YAML") from exc

    if not isinstance(data, Mapping):
        raise MemoryConfigError("Memory rules must be a mapping")

    return dict(data)


def _section(rules: Mapping[str, Any], name: str) -> Dict[str, Any]:
    value = rules.get(name, {}) if isinstance(rules, Mapping) else {}
    if not isinstance(value, Mapping):
        raise MemoryConfigError(f"Section '{name}' must be a mapping")
    return dict(value)


def _coerce_int(value: Any, default: int | None = None) -> int | None:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalise_rules(rules: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    short_term = _section(rules, "short_term")
    mid_term = _section(rules, "mid_term")
    long_term = _section(rules, "long_term")
    consolidation = _section(rules, "consolidation")

    return {
        "short_term": {
            "default_ttl_seconds": _coerce_int(short_term.get("default_ttl_seconds")),
            "max_items_per_session": _coerce_int(short_term.get("max_items_per_session")),
            "promotion_importance_threshold": _coerce_float(short_term.get("promotion_importance_threshold", 1.0), 1.0),
        },
        "mid_term": {
            "default_ttl_seconds": _coerce_int(mid_term.get("default_ttl_seconds")),
            "reinforcement_increment": _coerce_float(mid_term.get("reinforcement_increment", 1.0), 1.0),
            "promotion_strength_threshold": _coerce_float(mid_term.get("promotion_strength_threshold", float("inf")), float("inf")),
            "importance_promotion_threshold": _coerce_float(mid_term.get("importance_promotion_threshold", 1.0), 1.0),
            "pinned_ttl_seconds": _coerce_int(mid_term.get("pinned_ttl_seconds")),
        },
        "long_term": {
            "summary_max_chars": _coerce_int(long_term.get("summary_max_chars")),
            "require_confirmation": bool(long_term.get("require_confirmation", False)),
            "demotion_score_threshold": _coerce_float(long_term.get("demotion_score_threshold", float("-inf")), float("-inf")),
        },
        "consolidation": {
            "promotion_batch_size": _coerce_int(consolidation.get("promotion_batch_size"), 0),
            "pin_user_flagged": bool(consolidation.get("pin_user_flagged", False)),
        },
    }


class MemoryManager:
    """Manage LOGOS short-, mid-, and long-term memory semantics."""

    def __init__(self, rules: Mapping[str, Any] | None = None) -> None:
        loaded_rules = rules or load_memory_rules()
        self._rules = _normalise_rules(loaded_rules)
        self._short_term: Dict[str, Dict[str, MemoryItem]] = {}
        self._mid_term: Dict[str, MemoryItem] = {}

    @property
    def rules(self) -> Dict[str, Dict[str, Any]]:
        return self._rules

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def get_short_term_items(self, session_id: str) -> List[MemoryItem]:
        return list(self._short_term.get(session_id, {}).values())

    def get_mid_term_items(self) -> List[MemoryItem]:
        return list(self._mid_term.values())

    def record_short_term(
        self,
        session_id: str,
        key: str,
        content: Any,
        *,
        importance: float = 0.0,
        tags: Iterable[str] | None = None,
        ttl_seconds: int | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> MemoryItem:
        now = self._now()
        ttl = ttl_seconds if ttl_seconds is not None else self._rules["short_term"].get("default_ttl_seconds")
        item = MemoryItem(
            id=uuid4().hex,
            key=key,
            content=content,
            created_at=now,
            last_used=now,
            importance=_coerce_float(importance, 0.0),
            strength=0.0,
            ttl_seconds=ttl,
            pinned=False,
            tags=tuple(tags or ()),
            scope="short_term",
            metadata=dict(metadata or {}),
        )
        session_mem = self._short_term.setdefault(session_id, {})
        session_mem[item.id] = item
        self._trim_short_term(session_id)
        return item

    def _trim_short_term(self, session_id: str) -> None:
        max_items = self._rules["short_term"].get("max_items_per_session")
        if max_items is None:
            return
        session_mem = self._short_term.get(session_id)
        if not session_mem:
            return
        while len(session_mem) > max_items:
            oldest_id = min(session_mem, key=lambda key: session_mem[key].created_at)
            session_mem.pop(oldest_id, None)

    def promote_short_term_to_mid_term(
        self,
        session_id: str,
        item_id: str,
        *,
        pinned: bool = False,
        importance: float | None = None,
        ttl_seconds: int | None = None,
    ) -> MemoryItem | None:
        session_mem = self._short_term.get(session_id, {})
        if item_id not in session_mem:
            return None

        source = session_mem[item_id]
        now = self._now()
        ttl = ttl_seconds if ttl_seconds is not None else self._rules["mid_term"].get("default_ttl_seconds")
        if pinned:
            pinned_ttl = self._rules["mid_term"].get("pinned_ttl_seconds")
            ttl = pinned_ttl if pinned_ttl is not None else ttl

        mid_item = MemoryItem(
            id=uuid4().hex,
            key=source.key,
            content=source.content,
            created_at=now,
            last_used=now,
            importance=_coerce_float(importance if importance is not None else source.importance, source.importance),
            strength=source.strength,
            ttl_seconds=ttl,
            pinned=pinned,
            tags=source.tags,
            scope="mid_term",
            metadata=dict(source.metadata),
        )
        self._mid_term[mid_item.id] = mid_item
        return mid_item

    def store_mid_term(
        self,
        key: str,
        content: Any,
        *,
        importance: float = 0.0,
        pinned: bool = False,
        ttl_seconds: int | None = None,
        tags: Iterable[str] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> MemoryItem:
        now = self._now()
        ttl = ttl_seconds if ttl_seconds is not None else self._rules["mid_term"].get("default_ttl_seconds")
        if pinned:
            pinned_ttl = self._rules["mid_term"].get("pinned_ttl_seconds")
            ttl = pinned_ttl if pinned_ttl is not None else ttl

        mid_item = MemoryItem(
            id=uuid4().hex,
            key=key,
            content=content,
            created_at=now,
            last_used=now,
            importance=_coerce_float(importance, 0.0),
            strength=0.0,
            ttl_seconds=ttl,
            pinned=pinned,
            tags=tuple(tags or ()),
            scope="mid_term",
            metadata=dict(metadata or {}),
        )
        self._mid_term[mid_item.id] = mid_item
        return mid_item

    def reinforce_mid_term(self, item_id: str, *, amount: float | None = None, now: datetime | None = None) -> MemoryItem | None:
        item = self._mid_term.get(item_id)
        if item is None:
            return None

        increment = amount if amount is not None else self._rules["mid_term"].get("reinforcement_increment", 0.0)
        item.reinforce(_coerce_float(increment, 0.0), now or self._now(), self._rules["mid_term"].get("default_ttl_seconds"))
        return item

    def evict_expired(self, now: datetime | None = None) -> List[str]:
        timestamp = now or self._now()
        expired: List[str] = []

        for session_id, items in list(self._short_term.items()):
            for item_id, item in list(items.items()):
                if item.is_expired(timestamp):
                    items.pop(item_id, None)
                    expired.append(item_id)
            if not items:
                self._short_term.pop(session_id, None)

        for item_id, item in list(self._mid_term.items()):
            if item.is_expired(timestamp):
                self._mid_term.pop(item_id, None)
                expired.append(item_id)

        return expired

    def _should_promote(self, item: MemoryItem) -> bool:
        if item.pinned:
            return True
        if item.importance >= self._rules["mid_term"].get("importance_promotion_threshold", 1.0):
            return True
        return item.strength >= self._rules["mid_term"].get("promotion_strength_threshold", float("inf"))

    def _summarise_content(self, content: Any) -> Any:
        max_chars = self._rules["long_term"].get("summary_max_chars")
        if isinstance(content, str) and max_chars and len(content) > max_chars:
            return f"{content[:max_chars]}…"
        return content

    def prepare_long_term_payload(self, item: MemoryItem) -> Dict[str, Any]:
        content = self._summarise_content(item.content)
        return {
            "id": item.id,
            "key": item.key,
            "content": content,
            "importance": item.importance,
            "strength": item.strength,
            "tags": list(item.tags),
            "created_at": item.created_at,
            "last_used": item.last_used,
            "metadata": dict(item.metadata),
            "pinned": item.pinned,
        }

    def consolidate(
        self,
        *,
        session_id: str | None = None,
        now: datetime | None = None,
        persist_fn: Callable[[MemoryItem, Dict[str, Any]], Any] | None = None,
    ) -> Dict[str, Any]:
        timestamp = now or self._now()
        expired = self.evict_expired(timestamp)
        promoted: List[str] = []
        persisted: List[str] = []

        if session_id:
            threshold = self._rules["short_term"].get("promotion_importance_threshold", 1.0)
            session_items = list(self._short_term.get(session_id, {}).values())[: self._rules["consolidation"].get("promotion_batch_size") or None]
            for item in session_items:
                if item.importance >= threshold:
                    mid_item = self.promote_short_term_to_mid_term(session_id, item.id, importance=item.importance)
                    if mid_item:
                        promoted.append(mid_item.id)

        for item in list(self._mid_term.values()):
            if self._should_promote(item):
                payload = self.prepare_long_term_payload(item)
                if persist_fn:
                    persist_fn(item, payload)
                persisted.append(item.id)
                if not item.pinned:
                    self._mid_term.pop(item.id, None)

        return {
            "expired": expired,
            "promoted": promoted,
            "persisted": persisted,
            "remaining_mid_term": len(self._mid_term),
        }


__all__ = [
    "MemoryConfigError",
    "MemoryItem",
    "MemoryManager",
    "load_memory_rules",
]
