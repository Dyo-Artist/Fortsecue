import asyncio
import pathlib
import sys

import pytest

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from logos.events.bus import InMemoryEventBus
from logos.events.types import EventEnvelope


async def _wait_for_items(stream, count: int) -> list[EventEnvelope]:
    items: list[EventEnvelope] = []
    for _ in range(count):
        items.append(await asyncio.wait_for(anext(stream), timeout=1.0))
    return items


@pytest.mark.asyncio
async def test_inmemory_bus_publish_receive_in_order() -> None:
    bus = InMemoryEventBus()
    stream = bus.subscribe()
    receive_task = asyncio.create_task(_wait_for_items(stream, 2))
    await asyncio.sleep(0)

    bus.publish(EventEnvelope(event_type="logos.test.one", producer="tests", payload={"n": 1}))
    bus.publish(EventEnvelope(event_type="logos.test.two", producer="tests", payload={"n": 2}))

    received = await asyncio.wait_for(receive_task, timeout=1.0)

    assert [item.event_type for item in received] == ["logos.test.one", "logos.test.two"]
    assert [item.payload["n"] for item in received] == [1, 2]

    await stream.aclose()


@pytest.mark.asyncio
async def test_inmemory_bus_broadcasts_to_multiple_subscribers() -> None:
    bus = InMemoryEventBus()
    stream_a = bus.subscribe()
    stream_b = bus.subscribe()

    first_a = asyncio.create_task(asyncio.wait_for(anext(stream_a), timeout=1.0))
    first_b = asyncio.create_task(asyncio.wait_for(anext(stream_b), timeout=1.0))
    await asyncio.sleep(0)

    event = EventEnvelope(event_type="logos.test.broadcast", producer="tests", payload={"ok": True})
    bus.publish(event)

    recv_a = await first_a
    recv_b = await first_b

    assert recv_a.event_id == event.event_id
    assert recv_b.event_id == event.event_id
    assert recv_a.payload == recv_b.payload == {"ok": True}

    await stream_a.aclose()
    await stream_b.aclose()


@pytest.mark.asyncio
async def test_subscriber_cleanup_allows_future_publishes() -> None:
    bus = InMemoryEventBus()
    transient = bus.subscribe()

    first_task = asyncio.create_task(asyncio.wait_for(anext(transient), timeout=1.0))
    await asyncio.sleep(0)
    bus.publish(EventEnvelope(event_type="logos.test.cleanup", producer="tests", payload={"step": 1}))
    first_event = await first_task
    assert first_event.payload["step"] == 1

    await transient.aclose()
    assert bus.subscriber_count == 0

    # Publishing with no subscribers should be a no-op and not raise.
    bus.publish(EventEnvelope(event_type="logos.test.cleanup", producer="tests", payload={"step": 2}))

    active = bus.subscribe()
    active_task = asyncio.create_task(asyncio.wait_for(anext(active), timeout=1.0))
    await asyncio.sleep(0)
    bus.publish(EventEnvelope(event_type="logos.test.cleanup", producer="tests", payload={"step": 3}))
    active_event = await active_task

    assert active_event.payload["step"] == 3

    await active.aclose()
