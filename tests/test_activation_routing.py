import pathlib
import sys

import asyncio

import pytest

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from logos.events.bus import InMemoryEventBus
from logos.events.types import EventEnvelope
from logos.meta.activation import ActivationGraph, WeightedEdge
from logos.meta.controller import MetaController


@pytest.mark.asyncio
async def test_activation_propagation_is_deterministic_for_fixed_seed(tmp_path) -> None:
    graph = ActivationGraph(
        edges=[
            WeightedEdge("module.a", "module.b", 0.5),
            WeightedEdge("module.b", "module.c", 0.4),
        ],
        base_activation={"module.a": 0.2},
        seed=17,
        propagation_steps=3,
        noise_scale=0.0,
    )

    first = graph.inject({"module.a": 0.7})
    second = graph.inject({"module.a": 0.7})

    assert first == second


@pytest.mark.asyncio
async def test_modules_run_only_when_activation_meets_threshold(tmp_path) -> None:
    config = tmp_path / "meta.yml"
    config.write_text(
        """
mode: shadow
activation_threshold: 0.6
activation_graph:
  seed: 11
  damping: 1.0
  propagation_steps: 1
  base_activation:
    module.belief_prior_adjuster: 0.1
event_injection:
  logos.test.trigger:
    module.belief_prior_adjuster: 0.3
""",
        encoding="utf-8",
    )

    bus = InMemoryEventBus()
    controller = MetaController(bus, config_path=config)
    event = EventEnvelope(event_type="logos.test.trigger", producer="tests")

    ran = controller.process_event(event)

    assert ran == []


@pytest.mark.asyncio
async def test_shadow_mode_emits_suggestions_not_projections(tmp_path) -> None:
    config = tmp_path / "meta.yml"
    config.write_text(
        """
mode: shadow
activation_threshold: 0.1
activation_graph:
  seed: 3
  damping: 1.0
  propagation_steps: 0
  base_activation:
    module.belief_prior_adjuster: 0.2
event_injection:
  logos.test.input:
    module.belief_prior_adjuster: 0.5
""",
        encoding="utf-8",
    )

    bus = InMemoryEventBus()
    controller = MetaController(bus, config_path=config)
    stream = bus.subscribe()

    first = asyncio.create_task(asyncio.wait_for(anext(stream), timeout=1.0))
    await asyncio.sleep(0)
    controller.process_event(EventEnvelope(event_type="logos.test.input", producer="tests"))

    suggestion_event = await first

    assert suggestion_event.event_type.startswith("logos.suggestion.")
    assert suggestion_event.producer == "logos.meta.controller"

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(anext(stream), timeout=0.05)

    await stream.aclose()
