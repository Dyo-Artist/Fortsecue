"""Redis Streams event bus backend for durable, replayable event delivery."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Mapping
from typing import Any, Protocol, cast

from .types import EventEnvelope

logger = logging.getLogger(__name__)


class RedisStreamsClientProtocol(Protocol):
    """Minimal redis client contract required by :class:`RedisStreamsEventBus`."""

    def xadd(self, name: str, fields: Mapping[str, str], maxlen: int | None = None, approximate: bool = True) -> str: ...

    def xgroup_create(self, name: str, groupname: str, id: str = "$", mkstream: bool = False) -> Any: ...

    def xreadgroup(
        self,
        groupname: str,
        consumername: str,
        streams: Mapping[str, str],
        count: int | None = None,
        block: int | None = None,
    ) -> list[tuple[str | bytes, list[tuple[str | bytes, dict[str | bytes, str | bytes]]]]]: ...

    def xack(self, name: str, groupname: str, *ids: str) -> int: ...


class RedisStreamsEventBus:
    """Event bus implementation backed by Redis Streams consumer groups."""

    def __init__(
        self,
        client: RedisStreamsClientProtocol,
        *,
        stream_key: str,
        consumer_group: str,
        consumer_name: str,
        read_count: int = 10,
        read_block_ms: int = 1_000,
        create_group: bool = True,
    ) -> None:
        self._client = client
        self._stream_key = stream_key
        self._consumer_group = consumer_group
        self._consumer_name = consumer_name
        self._read_count = read_count
        self._read_block_ms = read_block_ms
        self._create_group = create_group
        self._group_initialised = False

    @classmethod
    def from_redis_url(
        cls,
        redis_url: str,
        *,
        stream_key: str,
        consumer_group: str,
        consumer_name: str,
        read_count: int = 10,
        read_block_ms: int = 1_000,
    ) -> RedisStreamsEventBus | None:
        """Create a bus from Redis URL, or ``None`` if redis-py is unavailable."""
        try:
            import redis  # type: ignore
        except ImportError:
            logger.warning("redis-py is not installed; Redis Streams backend unavailable")
            return None

        client = cast(RedisStreamsClientProtocol, redis.Redis.from_url(redis_url, decode_responses=False))
        return cls(
            client,
            stream_key=stream_key,
            consumer_group=consumer_group,
            consumer_name=consumer_name,
            read_count=read_count,
            read_block_ms=read_block_ms,
        )

    def _ensure_group(self) -> None:
        if self._group_initialised or not self._create_group:
            return

        try:
            self._client.xgroup_create(
                self._stream_key,
                self._consumer_group,
                id="0",
                mkstream=True,
            )
        except Exception as exc:  # pragma: no cover - error type depends on redis client version
            if "BUSYGROUP" not in str(exc):
                raise
        finally:
            self._group_initialised = True

    @staticmethod
    def _decode(value: str | bytes) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return value

    def publish(self, event: EventEnvelope) -> None:
        envelope_dict = event.model_dump(mode="json")
        payload = json.dumps(envelope_dict, separators=(",", ":"))
        self._client.xadd(self._stream_key, {"event": payload})

    async def subscribe(self) -> AsyncIterator[EventEnvelope]:
        await asyncio.to_thread(self._ensure_group)

        while True:
            records = await asyncio.to_thread(
                self._client.xreadgroup,
                self._consumer_group,
                self._consumer_name,
                {self._stream_key: ">"},
                self._read_count,
                self._read_block_ms,
            )
            if not records:
                continue

            for _, entries in records:
                for redis_id_raw, fields in entries:
                    redis_id = self._decode(redis_id_raw)
                    event_raw = fields.get("event")
                    if event_raw is None:
                        event_raw = fields.get(b"event")
                    if event_raw is None:
                        logger.warning("Skipping Redis Stream message %s without 'event' field", redis_id)
                        continue

                    event_json = self._decode(event_raw)
                    event_payload = json.loads(event_json)
                    provenance = event_payload.get("provenance")
                    if not isinstance(provenance, dict):
                        provenance = {}
                    provenance.setdefault("redis_id", redis_id)
                    event_payload["provenance"] = provenance

                    envelope = EventEnvelope.model_validate(event_payload)
                    yield envelope
                    await asyncio.to_thread(
                        self._client.xack,
                        self._stream_key,
                        self._consumer_group,
                        redis_id,
                    )


__all__ = ["RedisStreamsClientProtocol", "RedisStreamsEventBus"]
