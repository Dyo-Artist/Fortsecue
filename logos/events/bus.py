"""Event bus abstractions and in-process backend for LOGOS."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from threading import Lock
from typing import Protocol

from .types import EventEnvelope


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


__all__ = ["EventBus", "InMemoryEventBus"]
