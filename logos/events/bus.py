"""Event bus abstractions and backend selection for LOGOS."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from threading import Lock
from typing import Protocol

from .types import EventEnvelope

logger = logging.getLogger(__name__)


class EventBus(Protocol):
    """Interface for publishing and subscribing to event envelopes."""

    def publish(self, event: EventEnvelope) -> None:
        """Publish an event to all subscribers."""

    def subscribe(self) -> AsyncIterator[EventEnvelope]:
        """Create a subscriber stream for receiving events."""


class InMemoryEventBus:
    """Simple in-process event bus using one asyncio.Queue per subscriber."""

    def __init__(self, queue_maxsize: int = 0) -> None:
        self._queue_maxsize = queue_maxsize
        self._subscribers: set[asyncio.Queue[EventEnvelope]] = set()
        self._subscribers_lock = Lock()

    def publish(self, event: EventEnvelope) -> None:
        with self._subscribers_lock:
            subscribers = list(self._subscribers)

        for queue in subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # If bounded queues are used in the future, drop oldest then enqueue newest.
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    continue

    async def _subscribe_generator(self) -> AsyncIterator[EventEnvelope]:
        queue: asyncio.Queue[EventEnvelope] = asyncio.Queue(maxsize=self._queue_maxsize)
        with self._subscribers_lock:
            self._subscribers.add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            with self._subscribers_lock:
                self._subscribers.discard(queue)

    def subscribe(self) -> AsyncIterator[EventEnvelope]:
        return self._subscribe_generator()

    @property
    def subscriber_count(self) -> int:
        with self._subscribers_lock:
            return len(self._subscribers)


def _resolve_redis_streams_event_bus() -> EventBus | None:
    from .redis_streams import RedisStreamsEventBus

    redis_url = os.getenv("LOGOS_REDIS_URL", "redis://localhost:6379/0")
    stream_key = os.getenv("LOGOS_REDIS_STREAM_KEY", "logos:events")
    consumer_group = os.getenv("LOGOS_REDIS_CONSUMER_GROUP", "logos-consumers")
    consumer_name = os.getenv("LOGOS_REDIS_CONSUMER_NAME", "logos-node")

    return RedisStreamsEventBus.from_redis_url(
        redis_url,
        stream_key=stream_key,
        consumer_group=consumer_group,
        consumer_name=consumer_name,
    )


def create_event_bus_from_env() -> EventBus:
    """Create an event bus backend based on environment configuration."""

    backend = os.getenv("LOGOS_EVENT_BUS_BACKEND", "memory").strip().lower()
    if backend == "redis_streams":
        try:
            redis_bus = _resolve_redis_streams_event_bus()
        except Exception as exc:
            logger.warning("Failed to initialise Redis Streams event bus; falling back to memory: %s", exc)
            return InMemoryEventBus()

        if redis_bus is None:
            logger.warning("Redis Streams backend requested but unavailable; falling back to memory")
            return InMemoryEventBus()

        return redis_bus

    if backend != "memory":
        logger.warning("Unknown LOGOS_EVENT_BUS_BACKEND='%s'; falling back to memory", backend)

    return InMemoryEventBus()


__all__ = ["EventBus", "InMemoryEventBus", "create_event_bus_from_env"]
