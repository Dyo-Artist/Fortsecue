from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

import yaml

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "knowledgebase" / "schema"
NODE_TYPES_PATH = SCHEMA_DIR / "node_types.yml"
RELATIONSHIP_TYPES_PATH = SCHEMA_DIR / "relationship_types.yml"
RULES_PATH = SCHEMA_DIR / "rules.yml"
VERSION_PATH = Path(__file__).resolve().parent.parent / "knowledgebase" / "versioning" / "schema.yml"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso_date(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.date().isoformat()


def _load_yaml(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    if not isinstance(data, Mapping):
        return {}
    return data


def _dump_yaml(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        yaml.safe_dump(payload, file, sort_keys=True)


@dataclass
class NodeTypeDefinition:
    properties: set[str] = field(default_factory=set)
    introduced_in_version: str | int | None = None
    concept_kind: str | None = None
    deprecated: bool = False
    usage_count: int = 0
    last_used: str | None = None
    success_score: float | None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "NodeTypeDefinition":
        props = raw.get("properties") or []
        return cls(
            properties=set(str(p) for p in props if p),
            introduced_in_version=raw.get("introduced_in_version"),
            concept_kind=raw.get("concept_kind"),
            deprecated=bool(raw.get("deprecated", False)),
            usage_count=int(raw.get("usage_count", 0) or 0),
            last_used=raw.get("last_used"),
            success_score=float(raw["success_score"]) if "success_score" in raw and raw.get("success_score") is not None else None,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "properties": sorted(self.properties),
            "introduced_in_version": self.introduced_in_version,
            "concept_kind": self.concept_kind,
            "deprecated": bool(self.deprecated),
            "usage_count": int(self.usage_count),
            "last_used": self.last_used,
            "success_score": self.success_score,
        }


@dataclass
class RelationshipTypeDefinition:
    properties: set[str] = field(default_factory=set)
    introduced_in_version: str | int | None = None
    deprecated: bool = False
    usage_count: int = 0
    last_used: str | None = None
    success_score: float | None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "RelationshipTypeDefinition":
        props = raw.get("properties") or []
        return cls(
            properties=set(str(p) for p in props if p),
            introduced_in_version=raw.get("introduced_in_version"),
            deprecated=bool(raw.get("deprecated", False)),
            usage_count=int(raw.get("usage_count", 0) or 0),
            last_used=raw.get("last_used"),
            success_score=float(raw["success_score"]) if "success_score" in raw and raw.get("success_score") is not None else None,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "properties": sorted(self.properties),
            "introduced_in_version": self.introduced_in_version,
            "deprecated": bool(self.deprecated),
            "usage_count": int(self.usage_count),
            "last_used": self.last_used,
            "success_score": self.success_score,
        }


class SchemaStore:
    """Read/write store for node and relationship type definitions."""

    def __init__(
        self,
        node_types_path: Path = NODE_TYPES_PATH,
        relationship_types_path: Path = RELATIONSHIP_TYPES_PATH,
        rules_path: Path = RULES_PATH,
        version_path: Path = VERSION_PATH,
        *,
        mutable: bool = True,
    ) -> None:
        self._node_types_path = node_types_path
        self._relationship_types_path = relationship_types_path
        self._rules_path = rules_path
        self._version_path = version_path
        self._mutable = mutable
        self._node_types = self._load_node_types()
        self._relationship_types = self._load_relationship_types()
        self._rules = self._load_rules()
        self._version_info = self._load_version()

    @property
    def node_types(self) -> Mapping[str, NodeTypeDefinition]:
        return self._node_types

    @property
    def relationship_types(self) -> Mapping[str, RelationshipTypeDefinition]:
        return self._relationship_types

    @property
    def version(self) -> str | int:
        return self._version_info.get("version", 1)

    def get_schema_convention(self, key: str, default: str | None = None) -> str | None:
        conventions = self._rules.get("schema_conventions") if isinstance(self._rules.get("schema_conventions"), Mapping) else {}
        value = conventions.get(key) if isinstance(conventions, Mapping) else None
        if value is None:
            return default
        return str(value)

    def _load_node_types(self) -> dict[str, NodeTypeDefinition]:
        raw = _load_yaml(self._node_types_path)
        entries = raw.get("node_types") if isinstance(raw.get("node_types"), Mapping) else raw
        node_types: dict[str, NodeTypeDefinition] = {}
        if isinstance(entries, Mapping):
            for label, definition in entries.items():
                if not isinstance(definition, Mapping):
                    continue
                node_types[str(label)] = NodeTypeDefinition.from_mapping(definition)
        return node_types

    def _load_relationship_types(self) -> dict[str, RelationshipTypeDefinition]:
        raw = _load_yaml(self._relationship_types_path)
        entries = (
            raw.get("relationship_types") if isinstance(raw.get("relationship_types"), Mapping) else raw
        )
        rel_types: dict[str, RelationshipTypeDefinition] = {}
        if isinstance(entries, Mapping):
            for rel, definition in entries.items():
                if not isinstance(definition, Mapping):
                    continue
                rel_types[str(rel)] = RelationshipTypeDefinition.from_mapping(definition)
        return rel_types

    def _load_rules(self) -> Mapping[str, Any]:
        rules = _load_yaml(self._rules_path)
        return rules if isinstance(rules, Mapping) else {}

    def _load_version(self) -> dict[str, Any]:
        info = _load_yaml(self._version_path)
        if not isinstance(info, Mapping):
            return {"version": 1, "last_updated": None}
        return {"version": info.get("version", 1), "last_updated": info.get("last_updated")}

    def _persist_node_types(self) -> None:
        if not self._mutable:
            return
        payload = {"node_types": {label: definition.to_mapping() for label, definition in sorted(self._node_types.items())}}
        _dump_yaml(self._node_types_path, payload)

    def _persist_relationship_types(self) -> None:
        if not self._mutable:
            return
        payload = {
            "relationship_types": {
                rel: definition.to_mapping() for rel, definition in sorted(self._relationship_types.items())
            }
        }
        _dump_yaml(self._relationship_types_path, payload)

    def _persist_version(self) -> None:
        if not self._mutable:
            return
        _dump_yaml(self._version_path, self._version_info)

    def _increment_version(self, now: datetime) -> None:
        current = int(self._version_info.get("version", 1) or 1)
        self._version_info["version"] = current + 1
        self._version_info["last_updated"] = now.isoformat()
        self._persist_version()

    def _staleness_rule(self) -> tuple[int | None, timedelta | None, float | None]:
        usage_rule = self._rules.get("usage_deprecation") if isinstance(self._rules.get("usage_deprecation"), Mapping) else {}
        min_usage = usage_rule.get("min_usage")
        min_usage_val = int(min_usage) if isinstance(min_usage, int) else None
        stale_days = usage_rule.get("stale_after_days")
        stale_delta = timedelta(days=int(stale_days)) if isinstance(stale_days, (int, float)) else None
        success_floor = self._rules.get("success_floor")
        success_val = float(success_floor) if isinstance(success_floor, (int, float)) else None
        return min_usage_val, stale_delta, success_val

    def _apply_deprecation_rules(self, entry: NodeTypeDefinition | RelationshipTypeDefinition, now: datetime) -> None:
        min_usage, stale_delta, success_floor = self._staleness_rule()
        if entry.deprecated:
            return
        last_used_dt = None
        if entry.last_used:
            try:
                parsed = datetime.fromisoformat(entry.last_used)
                last_used_dt = parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
            except ValueError:
                last_used_dt = None
        if min_usage is not None and entry.usage_count <= min_usage:
            if stale_delta is not None and last_used_dt is not None and last_used_dt + stale_delta < now:
                entry.deprecated = True
        if success_floor is not None and entry.success_score is not None and entry.success_score < success_floor:
            entry.deprecated = True

    def record_node_type(
        self,
        label: str,
        observed_properties: set[str] | None,
        *,
        concept_kind: str | None = None,
        success_score: float | None = None,
        now: datetime | None = None,
    ) -> None:
        timestamp = now or _utcnow()
        properties = observed_properties or set()
        entry = self._node_types.get(label)
        created = False
        if entry is None:
            entry = NodeTypeDefinition(
                properties=set(properties),
                introduced_in_version=self.version,
                concept_kind=concept_kind,
                deprecated=False,
                usage_count=0,
                last_used=None,
                success_score=success_score,
            )
            self._node_types[label] = entry
            created = True
        before_props = set(entry.properties)
        entry.properties |= set(properties)
        if concept_kind and not entry.concept_kind:
            entry.concept_kind = concept_kind
        entry.usage_count += 1
        entry.last_used = _iso_date(timestamp)
        if success_score is not None:
            entry.success_score = success_score
        self._apply_deprecation_rules(entry, timestamp)
        if created:
            self._increment_version(timestamp)
        if created or entry.properties != before_props or concept_kind or success_score is not None:
            self._persist_node_types()
        elif self._mutable:
            self._persist_node_types()

    def record_relationship_type(
        self,
        rel_type: str,
        observed_properties: set[str] | None,
        *,
        success_score: float | None = None,
        now: datetime | None = None,
    ) -> None:
        timestamp = now or _utcnow()
        properties = observed_properties or set()
        entry = self._relationship_types.get(rel_type)
        created = False
        if entry is None:
            entry = RelationshipTypeDefinition(
                properties=set(properties),
                introduced_in_version=self.version,
                deprecated=False,
                usage_count=0,
                last_used=None,
                success_score=success_score,
            )
            self._relationship_types[rel_type] = entry
            created = True
        before_props = set(entry.properties)
        entry.properties |= set(properties)
        entry.usage_count += 1
        entry.last_used = _iso_date(timestamp)
        if success_score is not None:
            entry.success_score = success_score
        self._apply_deprecation_rules(entry, timestamp)
        if created:
            self._increment_version(timestamp)
        if created or entry.properties != before_props or success_score is not None:
            self._persist_relationship_types()
        elif self._mutable:
            self._persist_relationship_types()


__all__ = [
    "NodeTypeDefinition",
    "RelationshipTypeDefinition",
    "SchemaStore",
    "NODE_TYPES_PATH",
    "RELATIONSHIP_TYPES_PATH",
    "RULES_PATH",
    "VERSION_PATH",
]
