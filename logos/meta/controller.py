"""Meta-controller orchestration for activation-driven module routing."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from logos.events.bus import EventBus
from logos.events.types import EventEnvelope
from logos.knowledgebase.store import DEFAULT_BASE_PATH
from logos.meta.activation import aggregate_event_injection, build_activation_graph
from logos.meta.models import ModuleContext, ModuleProtocol, Suggestion

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = DEFAULT_BASE_PATH / "rules" / "meta_controller.yml"


class MetaController:
    """Consumes EventBus events and routes activation across configured modules."""

    def __init__(
        self,
        event_bus: EventBus,
        *,
        config_path: Path | str | None = None,
    ) -> None:
        self.event_bus = event_bus
        self.config_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        self._config = self._load_config(self.config_path)
        self.mode = str(self._config.get("mode", "shadow")).strip().lower() or "shadow"
        self.loop_mode = str(
            self._config.get("experimentation", {}).get("learning_loop_mode", "unified")
        ).strip().lower()
        self.activation_threshold = float(self._config.get("activation_threshold", 0.45))
        self.allowed_active_pipelines = set(self._config.get("active_allowlist", {}).get("pipelines", []) or [])
        self.allowed_active_modules = set(self._config.get("active_allowlist", {}).get("modules", []) or [])
        self._event_injection = self._config.get("event_injection", {})
        self.activation_graph = build_activation_graph(self._config.get("activation_graph", {}))
        self.modules = self._build_modules()

    @staticmethod
    def is_enabled() -> bool:
        return os.getenv("LOGOS_META_CONTROLLER", "1").strip() not in {"0", "false", "False"}

    def _load_config(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            logger.info("meta_controller_config_missing", extra={"path": str(path)})
            return {}
        with path.open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
        if not isinstance(loaded, dict):
            return {}
        return loaded

    def _build_modules(self) -> dict[str, ModuleProtocol]:
        return {
            "module.belief_prior_adjuster": self._belief_prior_adjuster,
            "module.ontology_proposal_summariser": self._ontology_proposal_summariser,
            "module.learning_signal_router": self._learning_signal_router,
        }

    def _belief_prior_adjuster(
        self,
        event: EventEnvelope,
        context: ModuleContext,
    ) -> tuple[list[EventEnvelope], list[Suggestion]]:
        confidence = max(0.1, min(1.0, context.activation))
        return (
            [],
            [
                Suggestion(
                    suggestion_type="logos.suggestion.belief_prior_adjustment",
                    confidence=confidence,
                    payload={
                        "event_type": event.event_type,
                        "recommended_adjustment": round((context.activation - 0.5) * 0.4, 3),
                        "learning_loop_mode": context.event_loop_mode,
                    },
                )
            ],
        )

    def _ontology_proposal_summariser(
        self,
        event: EventEnvelope,
        context: ModuleContext,
    ) -> tuple[list[EventEnvelope], list[Suggestion]]:
        concepts = event.payload.get("candidate_concepts", []) if isinstance(event.payload, dict) else []
        candidate_count = len(concepts) if isinstance(concepts, list) else 0
        return (
            [],
            [
                Suggestion(
                    suggestion_type="logos.suggestion.ontology_proposal_summary",
                    confidence=max(0.1, min(1.0, context.activation)),
                    payload={
                        "event_type": event.event_type,
                        "candidate_count": candidate_count,
                        "summary": "meta-controller suggests ontology proposal review",
                    },
                )
            ],
        )

    def _learning_signal_router(
        self,
        event: EventEnvelope,
        context: ModuleContext,
    ) -> tuple[list[EventEnvelope], list[Suggestion]]:
        candidate_signals = []
        if isinstance(event.payload, dict):
            for key in ("feedback", "scores", "signals"):
                value = event.payload.get(key)
                if value is not None:
                    candidate_signals.append(key)

        return (
            [],
            [
                Suggestion(
                    suggestion_type="logos.suggestion.learning_signal_route",
                    confidence=max(0.1, min(1.0, context.activation)),
                    payload={
                        "event_type": event.event_type,
                        "signals": candidate_signals,
                        "persistence_tier": "mid_term" if context.activation < 0.75 else "long_term_candidate",
                    },
                )
            ],
        )

    def _publish_suggestion(self, suggestion: Suggestion, *, source_event: EventEnvelope) -> None:
        envelope = EventEnvelope(
            event_type=suggestion.suggestion_type,
            producer="logos.meta.controller",
            correlation_id=source_event.correlation_id or source_event.event_id,
            causation_id=source_event.event_id,
            confidence=suggestion.confidence,
            provenance={
                "component": "meta_controller",
                "mode": self.mode,
            },
            payload=suggestion.payload,
        )
        self.event_bus.publish(envelope)

    def _publish_if_allowed(self, event: EventEnvelope) -> None:
        if self.mode == "shadow":
            if event.event_type.startswith("logos.suggestion."):
                self.event_bus.publish(event)
            return

        if event.event_type.startswith("logos.suggestion."):
            self.event_bus.publish(event)
            return

        target_pipeline = event.payload.get("pipeline_id") if isinstance(event.payload, dict) else None
        target_module = event.payload.get("module_name") if isinstance(event.payload, dict) else None
        if target_pipeline and target_pipeline in self.allowed_active_pipelines:
            self.event_bus.publish(event)
            return
        if target_module and target_module in self.allowed_active_modules:
            self.event_bus.publish(event)

    def process_event(self, event: EventEnvelope) -> list[str]:
        if event.producer == "logos.meta.controller":
            return []

        injection = aggregate_event_injection(
            event_type=event.event_type,
            event_injection=self._event_injection,
        )
        activations = self.activation_graph.inject(injection)
        ran_modules: list[str] = []

        for module_name, module in self.modules.items():
            activation = activations.get(module_name, 0.0)
            if activation < self.activation_threshold:
                continue

            ran_modules.append(module_name)
            context = ModuleContext(
                activation=activation,
                mode=self.mode,
                event_loop_mode=self.loop_mode,
                metadata={"source_event_type": event.event_type},
            )
            events_out, suggestions_out = module(event, context)
            for suggestion in suggestions_out:
                self._publish_suggestion(suggestion, source_event=event)
            for event_out in events_out:
                self._publish_if_allowed(event_out)

        return ran_modules

    async def run_forever(self, stop_event: asyncio.Event | None = None) -> None:
        stop_event = stop_event or asyncio.Event()
        stream = self.event_bus.subscribe()
        try:
            while not stop_event.is_set():
                try:
                    event = await asyncio.wait_for(anext(stream), timeout=0.2)
                except asyncio.TimeoutError:
                    continue
                self.process_event(event)
        except asyncio.CancelledError:
            raise
        finally:
            await stream.aclose()
