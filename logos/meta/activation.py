"""Activation graph and deterministic propagation for meta-controller routing."""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class WeightedEdge:
    source: str
    target: str
    weight: float


class ActivationGraph:
    """Directed weighted graph used to compute module activation scores."""

    def __init__(
        self,
        *,
        edges: list[WeightedEdge] | None = None,
        base_activation: Mapping[str, float] | None = None,
        damping: float = 0.85,
        propagation_steps: int = 2,
        seed: int = 7,
        noise_scale: float = 0.0,
    ) -> None:
        self._edges = list(edges or [])
        self._base_activation = dict(base_activation or {})
        self._damping = float(damping)
        self._propagation_steps = max(0, int(propagation_steps))
        self._random = random.Random(seed)
        self._noise_scale = max(0.0, float(noise_scale))

    @property
    def module_names(self) -> set[str]:
        names = set(self._base_activation.keys())
        for edge in self._edges:
            names.add(edge.source)
            names.add(edge.target)
        return names

    def inject(self, initial_activation: Mapping[str, float] | None = None) -> dict[str, float]:
        activation = dict(self._base_activation)
        for module, value in (initial_activation or {}).items():
            activation[module] = activation.get(module, 0.0) + float(value)

        for _ in range(self._propagation_steps):
            propagated = dict(activation)
            for edge in self._edges:
                source_value = activation.get(edge.source, 0.0)
                propagated[edge.target] = propagated.get(edge.target, 0.0) + source_value * edge.weight

            for module in list(propagated.keys()):
                value = propagated[module] * self._damping
                if self._noise_scale > 0:
                    value += self._random.uniform(-self._noise_scale, self._noise_scale)
                propagated[module] = min(1.0, max(0.0, value))
            activation = propagated

        return activation


def build_activation_graph(config: Mapping[str, object]) -> ActivationGraph:
    edges_raw = config.get("edges", []) if isinstance(config, Mapping) else []
    base_activation = config.get("base_activation", {}) if isinstance(config, Mapping) else {}

    edges: list[WeightedEdge] = []
    for edge in edges_raw if isinstance(edges_raw, list) else []:
        if not isinstance(edge, Mapping):
            continue
        source = str(edge.get("from", "")).strip()
        target = str(edge.get("to", "")).strip()
        if not source or not target:
            continue
        edges.append(WeightedEdge(source=source, target=target, weight=float(edge.get("weight", 0.0))))

    return ActivationGraph(
        edges=edges,
        base_activation={str(k): float(v) for k, v in (base_activation.items() if isinstance(base_activation, Mapping) else [])},
        damping=float(config.get("damping", 0.85)) if isinstance(config, Mapping) else 0.85,
        propagation_steps=int(config.get("propagation_steps", 2)) if isinstance(config, Mapping) else 2,
        seed=int(config.get("seed", 7)) if isinstance(config, Mapping) else 7,
        noise_scale=float(config.get("noise_scale", 0.0)) if isinstance(config, Mapping) else 0.0,
    )


def aggregate_event_injection(
    *,
    event_type: str,
    event_injection: Mapping[str, object] | None,
) -> dict[str, float]:
    """Build per-module activation injection from config for an event type."""

    if not isinstance(event_injection, Mapping):
        return {}

    merged: dict[str, float] = defaultdict(float)
    wildcard = event_injection.get("*")
    for group in (wildcard, event_injection.get(event_type)):
        if not isinstance(group, Mapping):
            continue
        for module_name, value in group.items():
            merged[str(module_name)] += float(value)

    return dict(merged)
