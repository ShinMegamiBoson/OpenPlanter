"""Engine construction and model listing helpers.

Extracted from ``__main__`` so that both the CLI entry-point and the TUI
can build / rebuild engines without circular imports.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .config import PROVIDER_DEFAULT_MODELS, AgentConfig
from .engine import ModelFactory, RLMEngine
from .model import (
    AnthropicModel,
    EchoFallbackModel,
    ModelError,
    OpenAICompatibleModel,
    list_anthropic_models,
    list_openai_models,
    list_openrouter_models,
)
from .tools import WorkspaceTools

# Patterns that unambiguously identify a provider.
_ANTHROPIC_RE = re.compile(r"^claude", re.IGNORECASE)
_OPENAI_RE = re.compile(r"^(gpt|o[1-4]-|o[1-4]$|chatgpt|dall-e|tts-|whisper)", re.IGNORECASE)
_CEREBRAS_RE = re.compile(r"^(llama.*cerebras|qwen-3|gpt-oss|zai-glm)", re.IGNORECASE)
_GEMINI_RE = re.compile(r"^gemini-", re.IGNORECASE)


def infer_provider_for_model(model: str) -> str | None:
    """Return the likely provider for *model*, or ``None`` if ambiguous."""
    if "/" in model:
        return "openrouter"
    if _ANTHROPIC_RE.search(model):
        return "anthropic"
    if _CEREBRAS_RE.search(model):
        return "cerebras"
    if _OPENAI_RE.search(model):
        return "openai"
    if _GEMINI_RE.search(model):
        return "gemini"
    return None


def _validate_model_provider(model_name: str, provider: str) -> None:
    """Raise ``ModelError`` if *model_name* is clearly wrong for *provider*."""
    if provider == "openrouter":
        return
    inferred = infer_provider_for_model(model_name)
    if inferred is None or inferred == provider or inferred == "openrouter":
        return
    raise ModelError(
        f"Model '{model_name}' belongs to provider '{inferred}', "
        f"not '{provider}'. Use --provider {inferred} or pick a "
        f"model that matches the current provider."
    )


def _fetch_models_for_provider(cfg: AgentConfig, provider: str) -> list[dict[str, Any]]:
    if provider == "openai":
        if not cfg.openai_api_key:
            raise ModelError("OpenAI key not configured.")
        return list_openai_models(api_key=cfg.openai_api_key, base_url=cfg.openai_base_url)
    if provider == "anthropic":
        if not cfg.anthropic_api_key:
            raise ModelError("Anthropic key not configured.")
        return list_anthropic_models(api_key=cfg.anthropic_api_key, base_url=cfg.anthropic_base_url)
    if provider == "openrouter":
        if not cfg.openrouter_api_key:
            raise ModelError("OpenRouter key not configured.")
        return list_openrouter_models(api_key=cfg.openrouter_api_key, base_url=cfg.openrouter_base_url)
    if provider == "cerebras":
        if not cfg.cerebras_api_key:
            raise ModelError("Cerebras key not configured.")
        return list_openai_models(api_key=cfg.cerebras_api_key, base_url=cfg.cerebras_base_url)
    if provider == "gemini":
        if not cfg.gemini_api_key:
            raise ModelError("Gemini key not configured.")
        return list_openai_models(api_key=cfg.gemini_api_key, base_url=cfg.gemini_base_url)
    raise ModelError(f"Unknown provider: {provider}")


def _resolve_model_name(cfg: AgentConfig) -> str:
    selected = (cfg.model or "").strip()
    if selected and selected.lower() != "newest":
        return selected
    if selected and selected.lower() == "newest":
        try:
            models = _fetch_models_for_provider(cfg, cfg.provider)
        except ModelError as exc:
            raise ModelError(f"Failed to resolve newest model for provider '{cfg.provider}': {exc}") from exc
        if not models:
            raise ModelError(f"No models returned for provider '{cfg.provider}'.")
        return str(models[0]["id"])
    return PROVIDER_DEFAULT_MODELS.get(cfg.provider, "claude-opus-4-6")


def build_model_factory(cfg: AgentConfig) -> ModelFactory | None:
    """Return a factory that creates models by name + optional reasoning effort."""
    def _factory(model_name: str, reasoning_effort: str | None = None) -> AnthropicModel | OpenAICompatibleModel:
        provider = infer_provider_for_model(model_name)
        effort = reasoning_effort or cfg.reasoning_effort
        if provider == "anthropic" and cfg.anthropic_api_key:
            return AnthropicModel(
                model=model_name,
                api_key=cfg.anthropic_api_key,
                base_url=cfg.anthropic_base_url,
                reasoning_effort=effort,
            )
        if provider in ("openai", None) and cfg.openai_api_key:
            return OpenAICompatibleModel(
                model=model_name,
                api_key=cfg.openai_api_key,
                base_url=cfg.openai_base_url,
                reasoning_effort=effort,
            )
        if provider == "openrouter" and cfg.openrouter_api_key:
            return OpenAICompatibleModel(
                model=model_name,
                api_key=cfg.openrouter_api_key,
                base_url=cfg.openrouter_base_url,
                reasoning_effort=effort,
                extra_headers={
                    "HTTP-Referer": "https://github.com/openplanter",
                    "X-Title": "OpenPlanter",
                },
            )
        if provider == "cerebras" and cfg.cerebras_api_key:
            return OpenAICompatibleModel(
                model=model_name,
                api_key=cfg.cerebras_api_key,
                base_url=cfg.cerebras_base_url,
                reasoning_effort=effort,
            )
        if provider == "gemini" and cfg.gemini_api_key:
            return OpenAICompatibleModel(
                model=model_name,
                api_key=cfg.gemini_api_key,
                base_url=cfg.gemini_base_url,
                reasoning_effort=effort,
                strict_tools=False,
            )
        raise ModelError(f"No API key available for model '{model_name}' (provider={provider})")

    if cfg.anthropic_api_key or cfg.openai_api_key or cfg.openrouter_api_key or cfg.cerebras_api_key or cfg.gemini_api_key:
        return _factory
    return None


def build_engine(cfg: AgentConfig) -> RLMEngine:
    tools = WorkspaceTools(
        root=Path(cfg.workspace),
        shell=cfg.shell,
        command_timeout_sec=cfg.command_timeout_sec,
        max_shell_output_chars=cfg.max_shell_output_chars,
        max_file_chars=cfg.max_file_chars,
        max_files_listed=cfg.max_files_listed,
        max_search_hits=cfg.max_search_hits,
        exa_api_key=cfg.exa_api_key,
        exa_base_url=cfg.exa_base_url,
    )

    try:
        model_name = _resolve_model_name(cfg)
    except ModelError as exc:
        model: EchoFallbackModel | OpenAICompatibleModel | AnthropicModel = EchoFallbackModel(note=str(exc))
        return RLMEngine(model=model, tools=tools, config=cfg)

    _validate_model_provider(model_name, cfg.provider)

    if cfg.provider == "openai" and cfg.openai_api_key:
        model = OpenAICompatibleModel(
            model=model_name,
            api_key=cfg.openai_api_key,
            base_url=cfg.openai_base_url,
            reasoning_effort=cfg.reasoning_effort,
        )
    elif cfg.provider == "openrouter" and cfg.openrouter_api_key:
        model = OpenAICompatibleModel(
            model=model_name,
            api_key=cfg.openrouter_api_key,
            base_url=cfg.openrouter_base_url,
            reasoning_effort=cfg.reasoning_effort,
            extra_headers={
                "HTTP-Referer": "https://github.com/openplanter",
                "X-Title": "OpenPlanter",
            },
        )
    elif cfg.provider == "cerebras" and cfg.cerebras_api_key:
        model = OpenAICompatibleModel(
            model=model_name,
            api_key=cfg.cerebras_api_key,
            base_url=cfg.cerebras_base_url,
            reasoning_effort=cfg.reasoning_effort,
        )
    elif cfg.provider == "gemini" and cfg.gemini_api_key:
        model = OpenAICompatibleModel(
            model=model_name,
            api_key=cfg.gemini_api_key,
            base_url=cfg.gemini_base_url,
            reasoning_effort=cfg.reasoning_effort,
            strict_tools=False,
        )
    elif cfg.provider == "anthropic" and cfg.anthropic_api_key:
        model = AnthropicModel(
            model=model_name,
            api_key=cfg.anthropic_api_key,
            base_url=cfg.anthropic_base_url,
            reasoning_effort=cfg.reasoning_effort,
        )
    else:
        model = EchoFallbackModel()

    return RLMEngine(model=model, tools=tools, config=cfg, model_factory=build_model_factory(cfg))
