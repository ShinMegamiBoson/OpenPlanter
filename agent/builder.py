"""Engine construction and model listing helpers.

Extracted from ``__main__`` so that both the CLI entry-point and the TUI
can build / rebuild engines without circular imports.
"""

from __future__ import annotations

import re
from pathlib import Path

from .config import (
    ANTHROPIC_FOUNDRY_MODEL_PREFIX,
    AZURE_FOUNDRY_MODEL_PREFIX,
    PROVIDER_DEFAULT_MODELS,
    AgentConfig,
    is_foundry_anthropic_base_url,
    is_foundry_openai_base_url,
    resolve_anthropic_api_key,
    resolve_openai_api_key,
)
from .engine import RLMEngine
from .model import (
    AnthropicModel,
    EchoFallbackModel,
    ModelError,
    OpenAICompatibleModel,
    list_anthropic_models,
    list_ollama_models,
    list_openai_models,
    list_openrouter_models,
)
from .engine import ModelFactory
from .tools import WorkspaceTools

# Patterns that unambiguously identify a provider.
_ANTHROPIC_RE = re.compile(r"^claude", re.IGNORECASE)
_OPENAI_RE = re.compile(r"^(gpt|o[1-4]-|o[1-4]$|chatgpt|dall-e|tts-|whisper)", re.IGNORECASE)
_CEREBRAS_RE = re.compile(r"^(llama.*cerebras|qwen-3|gpt-oss)", re.IGNORECASE)
_ZAI_RE = re.compile(r"^(glm|zai-glm)", re.IGNORECASE)
_OLLAMA_RE = re.compile(
    r"^(llama|mistral|gemma|phi|codellama|deepseek|vicuna|tinyllama|"
    r"neural-chat|dolphin|wizardlm|orca|nous-hermes|command-r|qwen(?!-3))",
    re.IGNORECASE,
)


def infer_provider_for_model(model: str) -> str | None:
    """Return the likely provider for *model*, or ``None`` if ambiguous."""
    lowered = model.strip().lower()
    if lowered.startswith(ANTHROPIC_FOUNDRY_MODEL_PREFIX):
        return "anthropic"
    if lowered.startswith(AZURE_FOUNDRY_MODEL_PREFIX):
        return "openai"
    if "/" in model:
        return "openrouter"
    if _ANTHROPIC_RE.search(model):
        return "anthropic"
    if _CEREBRAS_RE.search(model):
        return "cerebras"
    if _ZAI_RE.search(model):
        return "zai"
    if _OPENAI_RE.search(model):
        return "openai"
    if _OLLAMA_RE.search(model):
        return "ollama"
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


def _fetch_models_for_provider(cfg: AgentConfig, provider: str) -> list[dict]:
    if provider == "openai":
        api_key = resolve_openai_api_key(
            cfg.openai_api_key,
            cfg.openai_base_url,
            cfg.openai_oauth_token,
        )
        if not api_key:
            raise ModelError(
                "OpenAI auth not configured. Set OPENAI_API_KEY, "
                "OPENPLANTER_OPENAI_API_KEY, OPENAI_OAUTH_TOKEN, "
                "or OPENPLANTER_OPENAI_OAUTH_TOKEN."
            )
        models = list_openai_models(api_key=api_key, base_url=cfg.openai_base_url)
        if is_foundry_openai_base_url(cfg.openai_base_url):
            return [
                {
                    **row,
                    "id": row["id"]
                    if str(row.get("id", "")).lower().startswith(AZURE_FOUNDRY_MODEL_PREFIX)
                    else f"{AZURE_FOUNDRY_MODEL_PREFIX}{row['id']}",
                }
                for row in models
            ]
        return models
    if provider == "anthropic":
        api_key = resolve_anthropic_api_key(cfg.anthropic_api_key, cfg.anthropic_base_url)
        if not api_key:
            raise ModelError("Anthropic key not configured.")
        models = list_anthropic_models(api_key=api_key, base_url=cfg.anthropic_base_url)
        if is_foundry_anthropic_base_url(cfg.anthropic_base_url):
            return [
                {
                    **row,
                    "id": row["id"]
                    if str(row.get("id", "")).lower().startswith(ANTHROPIC_FOUNDRY_MODEL_PREFIX)
                    else f"{ANTHROPIC_FOUNDRY_MODEL_PREFIX}{row['id']}",
                }
                for row in models
            ]
        return models
    if provider == "openrouter":
        if not cfg.openrouter_api_key:
            raise ModelError("OpenRouter key not configured.")
        return list_openrouter_models(api_key=cfg.openrouter_api_key, base_url=cfg.openrouter_base_url)
    if provider == "cerebras":
        if not cfg.cerebras_api_key:
            raise ModelError("Cerebras key not configured.")
        return list_openai_models(api_key=cfg.cerebras_api_key, base_url=cfg.cerebras_base_url)
    if provider == "zai":
        if not cfg.zai_api_key:
            raise ModelError("Z.AI key not configured.")
        return list_openai_models(api_key=cfg.zai_api_key, base_url=cfg.zai_base_url)
    if provider == "ollama":
        return list_ollama_models(base_url=cfg.ollama_base_url)
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
    return PROVIDER_DEFAULT_MODELS.get(cfg.provider, "anthropic-foundry/claude-opus-4-6")


def build_model_factory(cfg: AgentConfig) -> ModelFactory | None:
    """Return a factory that creates models by name + optional reasoning effort."""
    openai_api_key = resolve_openai_api_key(
        cfg.openai_api_key,
        cfg.openai_base_url,
        cfg.openai_oauth_token,
    )
    anthropic_api_key = resolve_anthropic_api_key(cfg.anthropic_api_key, cfg.anthropic_base_url)

    def _factory(model_name: str, reasoning_effort: str | None = None) -> AnthropicModel | OpenAICompatibleModel:
        provider = infer_provider_for_model(model_name)
        effort = reasoning_effort or cfg.reasoning_effort
        if provider == "anthropic" and anthropic_api_key:
            return AnthropicModel(
                model=model_name,
                api_key=anthropic_api_key,
                base_url=cfg.anthropic_base_url,
                reasoning_effort=effort,
            )
        if provider in ("openai", None) and openai_api_key:
            return OpenAICompatibleModel(
                model=model_name,
                api_key=openai_api_key,
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
        if provider == "zai" and cfg.zai_api_key:
            thinking_type = "disabled" if effort in (None, "", "none") else "enabled"
            return OpenAICompatibleModel(
                model=model_name,
                api_key=cfg.zai_api_key,
                base_url=cfg.zai_base_url,
                reasoning_effort=effort,
                thinking_type=thinking_type,
                extra_headers={"Accept-Language": "en-US,en"},
                provider="zai",
                stream_max_retries=cfg.zai_stream_max_retries,
            )
        if provider == "ollama":
            return OpenAICompatibleModel(
                model=model_name,
                api_key="ollama",
                base_url=cfg.ollama_base_url,
                reasoning_effort=effort,
                first_byte_timeout=120,
                strict_tools=False,
            )
        raise ModelError(f"No API key available for model '{model_name}' (provider={provider})")

    if (
        anthropic_api_key
        or openai_api_key
        or cfg.openrouter_api_key
        or cfg.cerebras_api_key
        or cfg.zai_api_key
        or cfg.ollama_base_url
    ):
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
        web_search_provider=cfg.web_search_provider,
        exa_api_key=cfg.exa_api_key,
        exa_base_url=cfg.exa_base_url,
        firecrawl_api_key=cfg.firecrawl_api_key,
        firecrawl_base_url=cfg.firecrawl_base_url,
        brave_api_key=cfg.brave_api_key,
        brave_base_url=cfg.brave_base_url,
        tavily_api_key=cfg.tavily_api_key,
        tavily_base_url=cfg.tavily_base_url,
    )

    try:
        model_name = _resolve_model_name(cfg)
    except ModelError as exc:
        model = EchoFallbackModel(note=str(exc))
        return RLMEngine(model=model, tools=tools, config=cfg)

    _validate_model_provider(model_name, cfg.provider)

    openai_api_key = resolve_openai_api_key(
        cfg.openai_api_key,
        cfg.openai_base_url,
        cfg.openai_oauth_token,
    )
    anthropic_api_key = resolve_anthropic_api_key(cfg.anthropic_api_key, cfg.anthropic_base_url)

    if cfg.provider == "openai" and openai_api_key:
        model = OpenAICompatibleModel(
            model=model_name,
            api_key=openai_api_key,
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
    elif cfg.provider == "zai" and cfg.zai_api_key:
        thinking_type = "disabled" if cfg.reasoning_effort in (None, "", "none") else "enabled"
        model = OpenAICompatibleModel(
            model=model_name,
            api_key=cfg.zai_api_key,
            base_url=cfg.zai_base_url,
            reasoning_effort=cfg.reasoning_effort,
            thinking_type=thinking_type,
            extra_headers={"Accept-Language": "en-US,en"},
            provider="zai",
            stream_max_retries=cfg.zai_stream_max_retries,
        )
    elif cfg.provider == "ollama":
        model = OpenAICompatibleModel(
            model=model_name,
            api_key="ollama",
            base_url=cfg.ollama_base_url,
            reasoning_effort=cfg.reasoning_effort,
            first_byte_timeout=120,
            strict_tools=False,
        )
    elif cfg.provider == "anthropic" and anthropic_api_key:
        model = AnthropicModel(
            model=model_name,
            api_key=anthropic_api_key,
            base_url=cfg.anthropic_base_url,
            reasoning_effort=cfg.reasoning_effort,
        )
    else:
        model = EchoFallbackModel()

    return RLMEngine(model=model, tools=tools, config=cfg, model_factory=build_model_factory(cfg))
