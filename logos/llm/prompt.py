from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import yaml
from jinja2 import StrictUndefined, Template, TemplateError

from logos.interfaces.ollama_client import OllamaError, call_llm


class PromptEngineError(RuntimeError):
    """Raised when prompt loading, rendering, or execution fails."""


class PromptEngine:
    """Load, render, and execute knowledgebase prompt templates.

    Prompt templates are rendered from the knowledgebase, then executed against
    the local LLM backend.
    """

    def __init__(self, prompts_root: Path | None = None) -> None:
        base_dir = Path(__file__).resolve().parent.parent
        self.prompts_root = prompts_root or (base_dir / "knowledgebase" / "prompts")

    def _load_prompt_definition(self, relative_prompt_path: str) -> Mapping[str, Any]:
        prompt_path = (self.prompts_root / relative_prompt_path).resolve()
        if not prompt_path.exists() or not prompt_path.is_file():
            raise PromptEngineError(f"Prompt file not found: {prompt_path}")

        with prompt_path.open("r", encoding="utf-8") as file:
            data = yaml.safe_load(file) or {}

        if not isinstance(data, Mapping):
            raise PromptEngineError(f"Prompt file must contain a mapping: {prompt_path}")

        return data

    @staticmethod
    def _normalise_context(context: Mapping[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for key, value in context.items():
            if isinstance(value, (dict, list)):
                payload[key] = json.dumps(value, indent=2, sort_keys=True)
            elif value is None:
                payload[key] = ""
            else:
                payload[key] = value
        return payload

    def render_prompt(self, relative_prompt_path: str, context: Mapping[str, Any]) -> str:
        prompt_data = self._load_prompt_definition(relative_prompt_path)
        template_text = prompt_data.get("prompt_template") or prompt_data.get("template")
        if not isinstance(template_text, str) or not template_text.strip():
            raise PromptEngineError(f"Prompt template missing in {relative_prompt_path}")

        try:
            template = Template(template_text, undefined=StrictUndefined)
            return template.render(**self._normalise_context(context)).strip()
        except TemplateError as exc:
            raise PromptEngineError(f"Failed to render prompt: {relative_prompt_path}") from exc

    def run_prompt(self, relative_prompt_path: str, context: Mapping[str, Any]) -> str:
        prompt = self.render_prompt(relative_prompt_path, context)
        try:
            return call_llm(prompt).strip()
        except OllamaError as exc:
            raise PromptEngineError(
                "Local LLM backend unavailable; prompt execution failed."
            ) from exc
