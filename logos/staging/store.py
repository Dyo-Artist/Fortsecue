"""Staging store interface and local filesystem/SQLite implementation."""
from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Optional

from logos.models.bundles import InteractionMeta, PreviewBundle

StagingState = Literal["draft", "preview_ready", "committed", "failed"]


@dataclass
class InteractionState:
    """State snapshot for an interaction."""

    interaction_id: str
    state: StagingState
    received_at: datetime
    updated_at: datetime
    error_message: Optional[str] = None
    raw_path: Optional[Path] = None
    preview_path: Optional[Path] = None


class StagingStore:
    """Interface for persisting staging artefacts locally."""

    def create_interaction(self, meta: InteractionMeta) -> InteractionMeta:
        raise NotImplementedError

    def save_raw_file(self, interaction_id: str, content: bytes, filename: str, mime_type: str) -> Path:
        raise NotImplementedError

    def save_raw_text(self, interaction_id: str, text: str) -> Path:
        raise NotImplementedError

    def save_preview(self, interaction_id: str, preview: PreviewBundle) -> None:
        raise NotImplementedError

    def get_preview(self, interaction_id: str) -> PreviewBundle:
        raise NotImplementedError

    def set_state(self, interaction_id: str, state: StagingState, error_message: str | None = None) -> None:
        raise NotImplementedError

    def get_state(self, interaction_id: str) -> InteractionState:
        raise NotImplementedError

    def prune(self, max_age_days: int = 30) -> int:
        """Delete previews older than ``max_age_days`` when finalised."""

        raise NotImplementedError


class LocalStagingStore(StagingStore):
    """Filesystem + SQLite staging persistence."""

    def __init__(self, base_path: Path | str | None = None) -> None:
        self.base_path = Path(base_path or os.getenv("LOGOS_STAGING_DIR", Path(".logos") / "staging"))
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.index_path = self.base_path / "index.sqlite"
        self._ensure_index()

    def _ensure_index(self) -> None:
        with sqlite3.connect(self.index_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS interactions (
                    interaction_id TEXT PRIMARY KEY,
                    state TEXT,
                    source_type TEXT,
                    source_uri TEXT,
                    created_by TEXT,
                    received_at TEXT,
                    updated_at TEXT,
                    error_message TEXT,
                    raw_path TEXT,
                    preview_path TEXT
                )
                """
            )
            conn.commit()

    def _interaction_dir(self, interaction_id: str) -> Path:
        return self.base_path / interaction_id

    def _atomic_write(self, path: Path, data: bytes | str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        if isinstance(data, (bytes, bytearray)):
            with open(tmp_path, "wb") as f:
                f.write(data)
        else:
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(data)
        os.replace(tmp_path, path)

    def create_interaction(self, meta: InteractionMeta) -> InteractionMeta:
        interaction_id = meta.interaction_id or meta.model_copy().interaction_id
        meta.interaction_id = interaction_id
        interaction_dir = self._interaction_dir(interaction_id)
        interaction_dir.mkdir(parents=True, exist_ok=True)

        meta_path = interaction_dir / "meta.json"
        self._atomic_write(meta_path, meta.model_dump_json(indent=2))

        received_at = meta.received_at or datetime.now(timezone.utc)
        now_iso = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.index_path) as conn:
            conn.execute(
                """
                INSERT INTO interactions (
                    interaction_id, state, source_type, source_uri, created_by,
                    received_at, updated_at, error_message, raw_path, preview_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(interaction_id) DO UPDATE SET
                    source_type=excluded.source_type,
                    source_uri=excluded.source_uri,
                    created_by=excluded.created_by,
                    received_at=excluded.received_at,
                    updated_at=excluded.updated_at
                """,
                (
                    interaction_id,
                    "draft",
                    meta.source_type,
                    meta.source_uri,
                    meta.created_by,
                    received_at.isoformat(),
                    now_iso,
                    None,
                    None,
                    None,
                ),
            )
            conn.commit()
        return meta

    def save_raw_file(self, interaction_id: str, content: bytes, filename: str, mime_type: str) -> Path:
        safe_name = Path(filename).name or "raw_input"
        raw_dir = self._interaction_dir(interaction_id) / "raw"
        target = raw_dir / safe_name
        self._atomic_write(target, content)
        self._update_paths(interaction_id, raw_path=str(target))
        return target

    def save_raw_text(self, interaction_id: str, text: str) -> Path:
        raw_dir = self._interaction_dir(interaction_id) / "raw"
        target = raw_dir / "input.txt"
        self._atomic_write(target, text)
        self._update_paths(interaction_id, raw_path=str(target))
        return target

    def save_preview(self, interaction_id: str, preview: PreviewBundle) -> None:
        target = self._interaction_dir(interaction_id) / "preview.json"
        self._atomic_write(target, preview.model_dump_json(indent=2))
        self._update_paths(interaction_id, preview_path=str(target))

    def _update_paths(self, interaction_id: str, raw_path: str | None = None, preview_path: str | None = None) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.index_path) as conn:
            conn.execute("BEGIN")
            conn.execute(
                "UPDATE interactions SET updated_at=?, raw_path=COALESCE(?, raw_path), preview_path=COALESCE(?, preview_path) WHERE interaction_id=?",
                (now_iso, raw_path, preview_path, interaction_id),
            )
            conn.commit()

    def get_preview(self, interaction_id: str) -> PreviewBundle:
        path = self._interaction_dir(interaction_id) / "preview.json"
        if not path.exists():
            raise FileNotFoundError(f"Preview missing for interaction {interaction_id}")
        data = json.loads(path.read_text(encoding="utf-8"))
        return PreviewBundle.model_validate(data)

    def set_state(self, interaction_id: str, state: StagingState, error_message: str | None = None) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.index_path) as conn:
            conn.execute(
                "UPDATE interactions SET state=?, updated_at=?, error_message=? WHERE interaction_id=?",
                (state, now_iso, error_message, interaction_id),
            )
            if conn.total_changes == 0:
                conn.execute(
                    """
                    INSERT INTO interactions (
                        interaction_id, state, source_type, source_uri, created_by,
                        received_at, updated_at, error_message, raw_path, preview_path
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        interaction_id,
                        state,
                        None,
                        None,
                        None,
                        now_iso,
                        now_iso,
                        error_message,
                        None,
                        None,
                    ),
                )
            conn.commit()

    def get_state(self, interaction_id: str) -> InteractionState:
        with sqlite3.connect(self.index_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                "SELECT interaction_id, state, received_at, updated_at, error_message, raw_path, preview_path FROM interactions WHERE interaction_id=?",
                (interaction_id,),
            )
            row = cur.fetchone()
        if not row:
            raise KeyError(interaction_id)
        return InteractionState(
            interaction_id=row["interaction_id"],
            state=row["state"],
            received_at=datetime.fromisoformat(row["received_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            error_message=row["error_message"],
            raw_path=Path(row["raw_path"]) if row["raw_path"] else None,
            preview_path=Path(row["preview_path"]) if row["preview_path"] else None,
        )

    def prune(self, max_age_days: int = 30) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        removed = 0
        with sqlite3.connect(self.index_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT interaction_id, state, preview_path FROM interactions WHERE updated_at < ? AND state IN ('committed','failed')",
                (cutoff.isoformat(),),
            ).fetchall()
            for row in rows:
                if row["preview_path"]:
                    try:
                        Path(row["preview_path"]).unlink(missing_ok=True)
                        removed += 1
                    except OSError:
                        pass
                try:
                    (self._interaction_dir(row["interaction_id"])).rmdir()
                except OSError:
                    pass
                conn.execute("DELETE FROM interactions WHERE interaction_id=?", (row["interaction_id"],))
            conn.commit()
        return removed


__all__ = [
    "InteractionState",
    "LocalStagingStore",
    "StagingState",
    "StagingStore",
]
