"""Real-time update dispatcher for LOGOS."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import WebSocket
from pydantic import BaseModel, ConfigDict, Field

from logos.graphio.upsert import InteractionBundle

logger = logging.getLogger(__name__)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class GraphUpdateEvent(BaseModel):
    """Structured payload describing graph upserts for subscribers."""

    model_config = ConfigDict(extra="ignore")

    type: str = "graph_update"
    interaction_id: str
    committed_at: datetime
    interaction: Dict[str, Any]
    entities: Dict[str, List[Dict[str, Any]]] = Field(default_factory=dict)
    relationships: List[Dict[str, Any]] = Field(default_factory=list)
    summary: Dict[str, int] = Field(default_factory=dict)


def build_graph_update_event(
    bundle: InteractionBundle, committed_at: datetime | None = None
) -> GraphUpdateEvent:
    """Construct a serialisable graph update payload from an upsert bundle."""

    committed = _ensure_utc(committed_at or datetime.now(timezone.utc))
    interaction_data = bundle.interaction.model_dump(mode="json")

    entities = {
        "stakeholder_types": [item.model_dump(mode="json") for item in bundle.entities.stakeholder_types],
        "risk_categories": [item.model_dump(mode="json") for item in bundle.entities.risk_categories],
        "topic_groups": [item.model_dump(mode="json") for item in bundle.entities.topic_groups],
        "orgs": [item.model_dump(mode="json") for item in bundle.entities.orgs],
        "persons": [item.model_dump(mode="json") for item in bundle.entities.persons],
        "projects": [item.model_dump(mode="json") for item in bundle.entities.projects],
        "contracts": [item.model_dump(mode="json") for item in bundle.entities.contracts],
        "topics": [item.model_dump(mode="json") for item in bundle.entities.topics],
        "commitments": [item.model_dump(mode="json") for item in bundle.entities.commitments],
        "issues": [item.model_dump(mode="json") for item in bundle.entities.issues],
        "risks": [item.model_dump(mode="json") for item in bundle.entities.risks],
        "outcomes": [item.model_dump(mode="json") for item in bundle.entities.outcomes],
    }
    relationships = [item.model_dump(mode="json") for item in bundle.relationships]

    summary = {key: len(items) for key, items in entities.items()}
    summary["relationships"] = len(relationships)

    return GraphUpdateEvent(
        interaction_id=bundle.interaction.id,
        committed_at=committed,
        interaction=interaction_data,
        entities=entities,
        relationships=relationships,
        summary=summary,
    )


class UpdateBroadcaster:
    """Manage websocket subscribers and broadcast update payloads to all listeners."""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def register(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)

    async def unregister(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)

    async def broadcast(self, message: GraphUpdateEvent | Dict[str, Any]) -> None:
        payload = message.model_dump(mode="json") if isinstance(message, GraphUpdateEvent) else message
        async with self._lock:
            connections = list(self._connections)

        stale: list[WebSocket] = []
        for websocket in connections:
            try:
                await websocket.send_json(payload)
            except Exception:  # pragma: no cover - defensive guard to drop dead sockets
                stale.append(websocket)

        for websocket in stale:
            await self.unregister(websocket)

    def queue_broadcast(self, message: GraphUpdateEvent | Dict[str, Any]) -> None:
        """Schedule a broadcast from synchronous contexts."""

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("Graph update broadcast skipped because no event loop is running")
            return

        loop.create_task(self.broadcast(message))

    @property
    def subscriber_count(self) -> int:
        return len(self._connections)


update_broadcaster = UpdateBroadcaster()

__all__ = [
    "GraphUpdateEvent",
    "UpdateBroadcaster",
    "build_graph_update_event",
    "update_broadcaster",
]
