import asyncio
import json
import pathlib
import sys
from collections.abc import Mapping

import pytest

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from logos.events.redis_streams import RedisStreamsEventBus
from logos.events.types import EventEnvelope


class FakeRedisStreamsClient:
    def __init__(self) -> None:
        self._messages: list[tuple[str, dict[str, str]]] = []
        self._next_id = 1
        self._group_offsets: dict[str, int] = {}
        self.acks: list[tuple[str, str, str]] = []

    def xadd(self, name: str, fields: Mapping[str, str], maxlen: int | None = None, approximate: bool = True) -> str:
        message_id = f"{self._next_id}-0"
        self._next_id += 1
        self._messages.append((message_id, dict(fields)))
        return message_id

    def xgroup_create(self, name: str, groupname: str, id: str = "$", mkstream: bool = False) -> bool:
        self._group_offsets.setdefault(groupname, 0)
        return True

    def xreadgroup(
        self,
        groupname: str,
        consumername: str,
        streams: Mapping[str, str],
        count: int | None = None,
        block: int | None = None,
    ) -> list[tuple[str, list[tuple[str, dict[str, str]]]]]:
        stream_name = next(iter(streams.keys()))
        offset = self._group_offsets.setdefault(groupname, 0)
        if offset >= len(self._messages):
            return []

        batch_size = count if count is not None else len(self._messages)
        batch = self._messages[offset : offset + batch_size]
        self._group_offsets[groupname] = offset + len(batch)
        return [(stream_name, batch)]

    def xack(self, name: str, groupname: str, *ids: str) -> int:
        for entry_id in ids:
            self.acks.append((name, groupname, entry_id))
        return len(ids)


@pytest.mark.asyncio
async def test_redis_streams_publish_then_subscribe_yields_events() -> None:
    fake = FakeRedisStreamsClient()
    bus = RedisStreamsEventBus(
        fake,
        stream_key="logos:events",
        consumer_group="logos-consumers",
        consumer_name="test-node",
        read_block_ms=5,
    )

    bus.publish(EventEnvelope(event_type="logos.test.one", producer="tests", payload={"n": 1}))
    stream = bus.subscribe()

    received = await asyncio.wait_for(anext(stream), timeout=1.0)

    assert received.event_type == "logos.test.one"
    assert received.payload["n"] == 1
    assert received.provenance["redis_id"] == "1-0"

    await stream.aclose()


@pytest.mark.asyncio
async def test_redis_streams_ack_called_after_message_consumed() -> None:
    fake = FakeRedisStreamsClient()
    bus = RedisStreamsEventBus(
        fake,
        stream_key="logos:events",
        consumer_group="logos-consumers",
        consumer_name="test-node",
        read_block_ms=5,
    )

    bus.publish(EventEnvelope(event_type="logos.test.ack", producer="tests", payload={"ok": True}))
    stream = bus.subscribe()

    first_event = await asyncio.wait_for(anext(stream), timeout=1.0)
    assert first_event.event_type == "logos.test.ack"
    assert fake.acks == []

    poll_task = asyncio.create_task(asyncio.wait_for(anext(stream), timeout=0.05))
    await asyncio.sleep(0)
    await asyncio.sleep(0.01)
    assert fake.acks == [("logos:events", "logos-consumers", "1-0")]

    poll_task.cancel()
    with pytest.raises((asyncio.TimeoutError, asyncio.CancelledError)):
        await poll_task

    await stream.aclose()


@pytest.mark.asyncio
async def test_redis_streams_ordering_is_preserved() -> None:
    fake = FakeRedisStreamsClient()
    bus = RedisStreamsEventBus(
        fake,
        stream_key="logos:events",
        consumer_group="logos-consumers",
        consumer_name="test-node",
        read_block_ms=5,
    )

    for n in (1, 2, 3):
        event_json = json.dumps(
            EventEnvelope(event_type=f"logos.test.{n}", producer="tests", payload={"n": n}).model_dump(mode="json")
        )
        fake.xadd("logos:events", {"event": event_json})

    stream = bus.subscribe()
    received = [await asyncio.wait_for(anext(stream), timeout=1.0) for _ in range(3)]

    assert [item.payload["n"] for item in received] == [1, 2, 3]

    await stream.aclose()
