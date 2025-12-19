from __future__ import annotations

import re
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

try:  # pragma: no cover - platform guard
    import fcntl
except ImportError:  # pragma: no cover - platform guard
    fcntl = None


DEFAULT_BASE_PATH = Path(__file__).resolve().parent
DEFAULT_ACTOR = "system"


class KnowledgebaseError(RuntimeError):
    """Raised when the knowledgebase cannot be read."""


class KnowledgebaseWriteError(RuntimeError):
    """Raised when the knowledgebase cannot be updated."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "item"


class KnowledgebaseStore:
    """
    Helper for reading and writing knowledgebase assets with versioning and changelog support.

    The store is intentionally local-first: all writes happen on disk under ``logos/knowledgebase``
    (or a caller-provided base path) with simple file locks to avoid concurrent corruption.
    """

    _process_lock = threading.Lock()

    def __init__(self, base_path: Path | str | None = None, *, actor: str = DEFAULT_ACTOR) -> None:
        self.base_path = Path(base_path) if base_path else DEFAULT_BASE_PATH
        self.actor = actor or DEFAULT_ACTOR
        self.versioning_path = self.base_path / "versioning"
        self.lock_dir = self.versioning_path / "locks"
        self.changelog_path = self.versioning_path / "changelog.yml"
        self.versioning_path.mkdir(parents=True, exist_ok=True)
        self.lock_dir.mkdir(parents=True, exist_ok=True)

    def _relative(self, path: Path) -> Path:
        try:
            return path.relative_to(self.base_path)
        except ValueError:
            return path

    def _lock_path(self, path: Path) -> Path:
        rel = self._relative(path).as_posix().replace("/", "_")
        return self.lock_dir / f"{rel}.lock"

    @contextmanager
    def _file_lock(self, path: Path):  # pragma: no cover - exercised indirectly
        lock_path = self._lock_path(path)
        with self._process_lock:
            with lock_path.open("w", encoding="utf-8") as lock_file:
                if fcntl:
                    fcntl.flock(lock_file, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    if fcntl:
                        fcntl.flock(lock_file, fcntl.LOCK_UN)

    def _load_yaml(self, path: Path) -> Any:
        if not path.exists():
            return {}

        try:
            with path.open("r", encoding="utf-8") as file:
                return yaml.safe_load(file) or {}
        except yaml.YAMLError as exc:  # pragma: no cover - defensive
            raise KnowledgebaseError(f"Failed to parse knowledgebase file {path}") from exc

    def _write_yaml(self, path: Path, data: Any, *, lock: bool = True) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if lock:
            with self._file_lock(path):
                self._write_yaml(path, data, lock=False)
            return

        with path.open("w", encoding="utf-8") as file:
            yaml.safe_dump(data, file, sort_keys=False, allow_unicode=True)

    def _ensure_metadata(self, data: Any) -> dict[str, Any]:
        metadata = data.get("metadata") if isinstance(data, Mapping) else None
        if not isinstance(metadata, dict):
            metadata = {"version": "0.0.0"}
        metadata.setdefault("version", "0.0.0")
        data["metadata"] = metadata
        return metadata

    def _bump_version(self, version: str | None) -> str:
        try:
            major, minor, patch = [int(part) for part in str(version or "0.0.0").split(".")]
        except ValueError:
            major, minor, patch = 0, 0, 0
        patch += 1
        return f"{major}.{minor}.{patch}"

    def _append_changelog(self, *, path: Path, change: str, version: str, details: Mapping[str, Any] | None = None) -> None:
        entry = {
            "timestamp": _utc_now(),
            "actor": self.actor,
            "path": self._relative(path).as_posix(),
            "change": change,
            "version": version,
            "details": dict(details or {}),
        }

        with self._file_lock(self.changelog_path):
            existing: list[dict[str, Any]] = []
            if self.changelog_path.exists():
                try:
                    existing_raw = self._load_yaml(self.changelog_path)
                    if isinstance(existing_raw, list):
                        existing = list(existing_raw)
                except KnowledgebaseError:
                    existing = []

            existing.append(entry)
            self._write_yaml(self.changelog_path, existing, lock=False)

    def _entry_matches(self, entry: Mapping[str, Any], candidate: Mapping[str, Any], unique_fields: Iterable[str]) -> bool:
        return all(entry.get(field) == candidate.get(field) for field in unique_fields)

    def _append_entry(
        self,
        *,
        file_path: Path,
        list_key: str,
        entry: Mapping[str, Any],
        unique_fields: Iterable[str] | None,
        reason: str,
    ) -> bool:
        with self._file_lock(file_path):
            data = self._load_yaml(file_path)
            if not isinstance(data, dict):
                data = {}

            items = data.setdefault(list_key, [])
            if not isinstance(items, list):
                raise KnowledgebaseWriteError(
                    f"Knowledgebase file {file_path} must hold a list under '{list_key}'"
                )

            unique_fields = list(unique_fields or [])
            for existing in items:
                if not isinstance(existing, Mapping):
                    continue
                if unique_fields and self._entry_matches(existing, entry, unique_fields):
                    return False
                if not unique_fields and existing == entry:
                    return False

            metadata = self._ensure_metadata(data)
            new_version = self._bump_version(metadata.get("version"))
            timestamp = _utc_now()
            metadata.update({"version": new_version, "updated_at": timestamp, "updated_by": self.actor})

            enriched = dict(entry)
            enriched.setdefault("added_on", timestamp)
            enriched.setdefault("added_by", self.actor)
            enriched.setdefault("added_in_version", new_version)

            items.append(enriched)
            data[list_key] = items
            data["metadata"] = metadata

            self._write_yaml(file_path, data, lock=False)

        self._append_changelog(path=file_path, change=reason, version=new_version, details=enriched)
        return True

    def add_obligation_phrase(
        self,
        phrase: str,
        *,
        lexicon_name: str = "obligation_phrases.yml",
        flags: Iterable[str] | None = None,
        reason: str | None = None,
    ) -> bool:
        regex_text = re.escape(phrase)
        entry: dict[str, Any] = {"regex": regex_text}
        if flags:
            entry["flags"] = list(flags)
        return self._append_entry(
            file_path=self.base_path / "lexicons" / lexicon_name,
            list_key="patterns",
            entry=entry,
            unique_fields=["regex"],
            reason=reason or "Learned new obligation phrase",
        )

    def add_lexicon_entry(
        self,
        *,
        lexicon_name: str,
        entry: Mapping[str, Any],
        list_key: str = "patterns",
        unique_fields: Iterable[str] | None = None,
        reason: str | None = None,
    ) -> bool:
        """Persist a generic lexicon entry so new patterns can be curated over time."""

        return self._append_entry(
            file_path=self.base_path / "lexicons" / lexicon_name,
            list_key=list_key,
            entry=entry,
            unique_fields=unique_fields,
            reason=reason or f"Updated lexicon {lexicon_name}",
        )

    def add_concept(
        self,
        concept_set: str,
        concept: Mapping[str, Any],
        *,
        reason: str | None = None,
        id_prefix: str | None = None,
    ) -> bool:
        id_prefix = id_prefix or concept_set[:3]
        candidate = dict(concept)
        if "id" not in candidate and candidate.get("name"):
            candidate["id"] = f"{id_prefix}_{_slugify(str(candidate['name']))}"
        return self._append_entry(
            file_path=self.base_path / "concepts" / f"{concept_set}.yml",
            list_key=concept_set,
            entry=candidate,
            unique_fields=["id"],
            reason=reason or f"Learned new concept for {concept_set}",
        )

    def add_node_type(self, node_type: Mapping[str, Any], *, reason: str | None = None) -> bool:
        candidate = dict(node_type)
        if "id" not in candidate and candidate.get("label"):
            candidate["id"] = f"nt_{_slugify(str(candidate['label']))}"
        return self._append_entry(
            file_path=self.base_path / "schema" / "node_types.yml",
            list_key="node_types",
            entry=candidate,
            unique_fields=["id"],
            reason=reason or "Registered new node type",
        )

    def add_relationship_type(self, rel_type: Mapping[str, Any], *, reason: str | None = None) -> bool:
        candidate = dict(rel_type)
        if "type" not in candidate and candidate.get("rel"):
            candidate["type"] = candidate["rel"]
        return self._append_entry(
            file_path=self.base_path / "schema" / "relationship_types.yml",
            list_key="relationship_types",
            entry=candidate,
            unique_fields=["type"],
            reason=reason or "Registered new relationship type",
        )

    def record_session_memory(
        self,
        session_id: str,
        summary: str,
        *,
        interactions: Iterable[Mapping[str, Any]] | None = None,
        reason: str | None = None,
    ) -> bool:
        entry: dict[str, Any] = {"session_id": session_id, "summary": summary}
        if interactions is not None:
            entry["interactions"] = list(interactions)

        return self._append_entry(
            file_path=self.base_path / "workflows" / "session_memory.yml",
            list_key="sessions",
            entry=entry,
            unique_fields=["session_id", "summary"],
            reason=reason or "Recorded session memory snapshot",
        )

    def add_sentiment_override(
        self,
        term: str,
        sentiment: Any,
        *,
        context: str | None = None,
        lexicon_name: str = "sentiment_overrides.yml",
        reason: str | None = None,
    ) -> bool:
        """Capture a sentiment override so domain terms can be re-weighted."""

        entry: dict[str, Any] = {"term": term, "sentiment": sentiment}
        if context:
            entry["context"] = context

        return self._append_entry(
            file_path=self.base_path / "lexicons" / lexicon_name,
            list_key="terms",
            entry=entry,
            unique_fields=["term", "context"],
            reason=reason or "Captured sentiment override",
        )

    def record_learning_signal(
        self,
        signal_type: str,
        payload: Mapping[str, Any],
        *,
        status: str = "pending",
        reason: str | None = None,
    ) -> bool:
        """Log learning signals for offline curation without enforcing immediate writes."""

        entry: dict[str, Any] = {
            "type": signal_type,
            "payload": dict(payload),
            "status": status,
        }

        return self._append_entry(
            file_path=self.base_path / "learning" / "signals.yml",
            list_key="signals",
            entry=entry,
            unique_fields=["type", "payload"],
            reason=reason or "Captured learning signal",
        )

    def update_prompt_template(self, prompt_name: str, template: str, *, reason: str | None = None) -> str:
        path = self.base_path / "prompts" / prompt_name
        with self._file_lock(path):
            data = self._load_yaml(path)
            if not isinstance(data, dict):
                data = {}

            metadata = self._ensure_metadata(data)
            if data.get("template") == template:
                return metadata.get("version", "0.0.0")

            new_version = self._bump_version(metadata.get("version"))
            timestamp = _utc_now()
            metadata.update({"version": new_version, "updated_at": timestamp, "updated_by": self.actor})

            data["template"] = template
            data["metadata"] = metadata

            self._write_yaml(path, data, lock=False)

        self._append_changelog(
            path=path,
            change=reason or "Updated prompt template",
            version=new_version,
            details={"template_preview": template[:80]},
        )
        return new_version

    def apply_learning_signals(self, signals: Mapping[str, Any] | None) -> dict[str, list[str]]:
        """Apply structured learning signals to mutate lexicons or record curation tasks."""

        updates: dict[str, list[str]] = {
            "lexicon_updates": [],
            "concept_updates": [],
            "schema_updates": [],
            "sentiment_updates": [],
            "learning_signals": [],
        }

        if not isinstance(signals, Mapping):
            return updates

        lexicon_patterns = signals.get("lexicon_patterns")
        if isinstance(lexicon_patterns, list):
            for pattern in lexicon_patterns:
                if isinstance(pattern, str):
                    entry = {"regex": re.escape(pattern)}
                    added = self.add_lexicon_entry(
                        lexicon_name="obligation_phrases.yml",
                        entry=entry,
                        unique_fields=["regex"],
                        reason="Learned lexicon pattern",
                    )
                    if added:
                        updates["lexicon_updates"].append(pattern)
                    if self.record_learning_signal(
                        "lexicon_pattern", {"pattern": pattern, "lexicon": "obligation_phrases.yml"},
                        reason="Queued lexicon learning signal",
                    ):
                        updates.setdefault("learning_signals", []).append("lexicon_pattern")
                elif isinstance(pattern, Mapping):
                    lexicon_name = pattern.get("lexicon") or "obligation_phrases.yml"
                    entry = dict(pattern)
                    entry.pop("lexicon", None)
                    added = self.add_lexicon_entry(
                        lexicon_name=lexicon_name,
                        entry=entry,
                        unique_fields=["regex", "term"],
                        reason="Learned lexicon pattern",
                    )
                    if added:
                        updates["lexicon_updates"].append(str(pattern))
                    if self.record_learning_signal(
                        "lexicon_pattern", {"pattern": entry, "lexicon": lexicon_name},
                        reason="Queued lexicon learning signal",
                    ):
                        updates.setdefault("learning_signals", []).append("lexicon_pattern")

        sentiment_overrides = signals.get("sentiment_overrides")
        if isinstance(sentiment_overrides, list):
            for override in sentiment_overrides:
                if not isinstance(override, Mapping):
                    continue
                term = override.get("term")
                sentiment = override.get("sentiment")
                context = override.get("context") if isinstance(override.get("context"), str) else None
                if isinstance(term, str):
                    added = self.add_sentiment_override(
                        term,
                        sentiment,
                        context=context,
                        reason="Recorded sentiment override",
                    )
                    if added:
                        updates["sentiment_updates"].append(term)
                    if self.record_learning_signal(
                        "sentiment_override",
                        {"term": term, "sentiment": sentiment, "context": context},
                        reason="Queued sentiment override",
                    ):
                        updates.setdefault("learning_signals", []).append("sentiment_override")

        schema_suggestions = signals.get("schema_suggestions")
        if isinstance(schema_suggestions, Mapping):
            for node_type in schema_suggestions.get("node_types", []):
                if isinstance(node_type, Mapping):
                    added = self.add_node_type(node_type, reason="Schema evolution from learning signal")
                    if added:
                        updates["schema_updates"].append(node_type.get("id") or node_type.get("label", ""))
                    if self.record_learning_signal("schema_node_type", node_type, reason="Queued schema learning signal"):
                        updates.setdefault("learning_signals", []).append("schema_node_type")
            for rel_type in schema_suggestions.get("relationship_types", []):
                if isinstance(rel_type, Mapping):
                    added = self.add_relationship_type(
                        rel_type,
                        reason="Schema evolution from learning signal",
                    )
                    if added:
                        updates["schema_updates"].append(rel_type.get("type") or rel_type.get("rel", ""))
                    if self.record_learning_signal("schema_relationship_type", rel_type, reason="Queued schema learning signal"):
                        updates.setdefault("learning_signals", []).append("schema_relationship_type")

        for signal_type, payload in (
            signals.items()
            if isinstance(signals, Mapping)
            else []
        ):
            if signal_type in {"lexicon_patterns", "sentiment_overrides", "schema_suggestions"}:
                continue
            if isinstance(payload, Mapping) or isinstance(payload, list):
                logged = self.record_learning_signal(signal_type, {"data": payload}, reason="Captured auxiliary signal")
                if logged:
                    updates.setdefault("learning_signals", []).append(signal_type)

        return updates

    def learn_from_extraction(self, extraction: Mapping[str, Any] | None, *, source_uri: str | None = None) -> dict[str, list[str]]:
        if extraction is None:
            return {
                "lexicon_updates": [],
                "concept_updates": [],
                "schema_updates": [],
                "sentiment_updates": [],
                "learning_signals": [],
            }

        updates = {
            "lexicon_updates": [],
            "concept_updates": [],
            "schema_updates": [],
            "sentiment_updates": [],
            "learning_signals": [],
        }
        entities = extraction.get("entities") if isinstance(extraction, Mapping) else None
        if isinstance(entities, Mapping):
            commitments = entities.get("commitments") if isinstance(entities.get("commitments"), list) else []
            for commitment in commitments:
                if isinstance(commitment, str) and self.add_obligation_phrase(
                    commitment,
                    reason=f"Learned obligation phrase from {source_uri or 'interaction'}",
                ):
                    updates["lexicon_updates"].append(commitment)

            persons = entities.get("persons") if isinstance(entities.get("persons"), list) else []
            for person in persons:
                if not isinstance(person, Mapping):
                    continue
                role = person.get("type") or person.get("role")
                if isinstance(role, str) and self.add_concept(
                    "stakeholder_types",
                    {"name": role, "description": f"Learned from {source_uri or 'interaction'}"},
                    reason=f"Captured stakeholder role '{role}'",
                    id_prefix="st",
                ):
                    updates["concept_updates"].append(role)

            risks = entities.get("risks") if isinstance(entities.get("risks"), list) else []
            for risk in risks:
                category = None
                if isinstance(risk, Mapping):
                    category = risk.get("category") or risk.get("type")
                elif isinstance(risk, str):
                    category = risk
                if isinstance(category, str) and self.add_concept(
                    "risk_categories",
                    {"name": category, "description": f"Learned from {source_uri or 'interaction'}"},
                    reason=f"Captured risk category '{category}'",
                    id_prefix="rc",
                ):
                    updates["concept_updates"].append(category)

        relationships = extraction.get("relationships") if isinstance(extraction, Mapping) else None
        if isinstance(relationships, list):
            for rel in relationships:
                if not isinstance(rel, Mapping):
                    continue
                rel_type = rel.get("rel") or rel.get("type")
                if isinstance(rel_type, str) and self.add_relationship_type(
                    {"type": rel_type, "description": f"Observed in {source_uri or 'interaction'}"},
                    reason=f"Observed relationship {rel_type}",
                ):
                    updates["schema_updates"].append(rel_type)

        learning_signals = extraction.get("learning_signals") if isinstance(extraction, Mapping) else None
        signal_updates = self.apply_learning_signals(learning_signals)
        for key, value in signal_updates.items():
            if isinstance(value, list):
                updates.setdefault(key, []).extend(value)

        return updates
