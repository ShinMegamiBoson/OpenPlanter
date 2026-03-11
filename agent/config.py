from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

AZURE_FOUNDRY_MODEL_PREFIX = "azure-foundry/"
ANTHROPIC_FOUNDRY_MODEL_PREFIX = "anthropic-foundry/"
FOUNDRY_OPENAI_BASE_URL = "https://foundry-proxy.cheetah-koi.ts.net/openai/v1"
FOUNDRY_ANTHROPIC_BASE_URL = "https://foundry-proxy.cheetah-koi.ts.net/anthropic/v1"
FOUNDRY_OPENAI_API_KEY_PLACEHOLDER = "dont-worry-this-key-will-be-auto-injected"
FOUNDRY_ANTHROPIC_API_KEY_PLACEHOLDER = "dont-worry-it-will-be-injected"
ZAI_PAYGO_BASE_URL = "https://api.z.ai/api/paas/v4"
ZAI_CODING_BASE_URL = "https://api.z.ai/api/coding/paas/v4"

PROVIDER_DEFAULT_MODELS: dict[str, str] = {
    "openai": "azure-foundry/gpt-5.3-codex",
    "anthropic": "anthropic-foundry/claude-opus-4-6",
    "openrouter": "anthropic/claude-sonnet-4-5",
    "cerebras": "qwen-3-235b-a22b-instruct-2507",
    "zai": "glm-5",
    "ollama": "llama3.2",
}

def normalize_zai_plan(value: str | None) -> str:
    text = (value or "").strip().lower()
    if text in {"paygo", "coding"}:
        return text
    return "paygo"


def resolve_zai_base_url(
    plan: str,
    *,
    paygo_base_url: str = ZAI_PAYGO_BASE_URL,
    coding_base_url: str = ZAI_CODING_BASE_URL,
) -> str:
    return coding_base_url if normalize_zai_plan(plan) == "coding" else paygo_base_url


def _normalize_base_url(url: str) -> str:
    return url.strip().rstrip("/")


def is_foundry_openai_base_url(url: str) -> bool:
    return _normalize_base_url(url) == FOUNDRY_OPENAI_BASE_URL


def is_foundry_anthropic_base_url(url: str) -> bool:
    return _normalize_base_url(url) == FOUNDRY_ANTHROPIC_BASE_URL


def resolve_openai_api_key(api_key: str | None, base_url: str) -> str | None:
    key = (api_key or "").strip() or None
    if key == FOUNDRY_OPENAI_API_KEY_PLACEHOLDER and not is_foundry_openai_base_url(base_url):
        return None
    if key:
        return key
    if is_foundry_openai_base_url(base_url):
        return FOUNDRY_OPENAI_API_KEY_PLACEHOLDER
    return None


def resolve_anthropic_api_key(api_key: str | None, base_url: str) -> str | None:
    key = (api_key or "").strip() or None
    if (
        key == FOUNDRY_ANTHROPIC_API_KEY_PLACEHOLDER
        and not is_foundry_anthropic_base_url(base_url)
    ):
        return None
    if key:
        return key
    if is_foundry_anthropic_base_url(base_url):
        return FOUNDRY_ANTHROPIC_API_KEY_PLACEHOLDER
    return None


def strip_foundry_model_prefix(model: str) -> str:
    text = model.strip()
    lower = text.lower()
    if lower.startswith(AZURE_FOUNDRY_MODEL_PREFIX):
        return text[len(AZURE_FOUNDRY_MODEL_PREFIX):]
    if lower.startswith(ANTHROPIC_FOUNDRY_MODEL_PREFIX):
        return text[len(ANTHROPIC_FOUNDRY_MODEL_PREFIX):]
    return text


@dataclass(slots=True)
class AgentConfig:
    workspace: Path
    provider: str = "auto"
    model: str = "anthropic-foundry/claude-opus-4-6"
    reasoning_effort: str | None = "high"
    base_url: str = FOUNDRY_OPENAI_BASE_URL  # Legacy alias for OpenAI-compatible base URL.
    api_key: str | None = None  # Legacy alias for OpenAI key.
    openai_base_url: str = FOUNDRY_OPENAI_BASE_URL
    anthropic_base_url: str = FOUNDRY_ANTHROPIC_BASE_URL
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    cerebras_base_url: str = "https://api.cerebras.ai/v1"
    zai_plan: str = "paygo"
    zai_paygo_base_url: str = ZAI_PAYGO_BASE_URL
    zai_coding_base_url: str = ZAI_CODING_BASE_URL
    zai_base_url: str = ZAI_PAYGO_BASE_URL
    ollama_base_url: str = "http://localhost:11434/v1"
    exa_base_url: str = "https://api.exa.ai"
    firecrawl_base_url: str = "https://api.firecrawl.dev/v1"
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    openrouter_api_key: str | None = None
    cerebras_api_key: str | None = None
    zai_api_key: str | None = None
    exa_api_key: str | None = None
    firecrawl_api_key: str | None = None
    web_search_provider: str = "exa"
    voyage_api_key: str | None = None
    max_depth: int = 4
    max_steps_per_call: int = 100
    max_observation_chars: int = 6000
    command_timeout_sec: int = 45
    shell: str = "/bin/sh"
    max_files_listed: int = 400
    max_file_chars: int = 20000
    max_search_hits: int = 200
    max_shell_output_chars: int = 16000
    session_root_dir: str = ".openplanter"
    max_persisted_observations: int = 400
    max_solve_seconds: int = 0
    rate_limit_max_retries: int = 12
    zai_stream_max_retries: int = 10
    rate_limit_backoff_base_sec: float = 1.0
    rate_limit_backoff_max_sec: float = 60.0
    rate_limit_retry_after_cap_sec: float = 120.0
    recursive: bool = True
    min_subtask_depth: int = 0
    acceptance_criteria: bool = True
    max_plan_chars: int = 40_000
    max_turn_summaries: int = 50
    demo: bool = False

    def __post_init__(self) -> None:
        self.openai_api_key = resolve_openai_api_key(self.openai_api_key, self.openai_base_url)
        self.anthropic_api_key = resolve_anthropic_api_key(
            self.anthropic_api_key, self.anthropic_base_url
        )
        self.api_key = resolve_openai_api_key(self.api_key, self.base_url)

    @classmethod
    def from_env(cls, workspace: str | Path) -> "AgentConfig":
        ws = Path(workspace).expanduser().resolve()
        openai_api_key = (
            os.getenv("OPENPLANTER_OPENAI_API_KEY")
            or os.getenv("OPENAI_API_KEY")
        )
        anthropic_api_key = os.getenv("OPENPLANTER_ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
        openrouter_api_key = os.getenv("OPENPLANTER_OPENROUTER_API_KEY") or os.getenv("OPENROUTER_API_KEY")
        cerebras_api_key = os.getenv("OPENPLANTER_CEREBRAS_API_KEY") or os.getenv("CEREBRAS_API_KEY")
        zai_api_key = os.getenv("OPENPLANTER_ZAI_API_KEY") or os.getenv("ZAI_API_KEY")
        exa_api_key = os.getenv("OPENPLANTER_EXA_API_KEY") or os.getenv("EXA_API_KEY")
        firecrawl_api_key = os.getenv("OPENPLANTER_FIRECRAWL_API_KEY") or os.getenv("FIRECRAWL_API_KEY")
        voyage_api_key = os.getenv("OPENPLANTER_VOYAGE_API_KEY") or os.getenv("VOYAGE_API_KEY")
        openai_base_url = os.getenv("OPENPLANTER_OPENAI_BASE_URL") or os.getenv(
            "OPENPLANTER_BASE_URL",
            FOUNDRY_OPENAI_BASE_URL,
        )
        anthropic_base_url = os.getenv(
            "OPENPLANTER_ANTHROPIC_BASE_URL",
            FOUNDRY_ANTHROPIC_BASE_URL,
        )
        openai_api_key = resolve_openai_api_key(openai_api_key, openai_base_url)
        anthropic_api_key = resolve_anthropic_api_key(anthropic_api_key, anthropic_base_url)
        zai_plan = normalize_zai_plan(os.getenv("OPENPLANTER_ZAI_PLAN", "paygo"))
        zai_paygo_base_url = os.getenv("OPENPLANTER_ZAI_PAYGO_BASE_URL", ZAI_PAYGO_BASE_URL)
        zai_coding_base_url = os.getenv("OPENPLANTER_ZAI_CODING_BASE_URL", ZAI_CODING_BASE_URL)
        zai_base_url_override = (os.getenv("OPENPLANTER_ZAI_BASE_URL", "") or "").strip()
        zai_base_url = (
            zai_base_url_override
            or resolve_zai_base_url(
                zai_plan,
                paygo_base_url=zai_paygo_base_url,
                coding_base_url=zai_coding_base_url,
            )
        )
        web_search_provider = (os.getenv("OPENPLANTER_WEB_SEARCH_PROVIDER", "exa").strip().lower() or "exa")
        if web_search_provider not in {"exa", "firecrawl"}:
            web_search_provider = "exa"
        return cls(
            workspace=ws,
            provider=os.getenv("OPENPLANTER_PROVIDER", "auto").strip().lower() or "auto",
            model=os.getenv("OPENPLANTER_MODEL", PROVIDER_DEFAULT_MODELS["anthropic"]),
            reasoning_effort=(os.getenv("OPENPLANTER_REASONING_EFFORT", "high").strip().lower() or None),
            base_url=openai_base_url,
            api_key=openai_api_key,
            openai_base_url=openai_base_url,
            anthropic_base_url=anthropic_base_url,
            openrouter_base_url=os.getenv("OPENPLANTER_OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            cerebras_base_url=os.getenv("OPENPLANTER_CEREBRAS_BASE_URL", "https://api.cerebras.ai/v1"),
            zai_plan=zai_plan,
            zai_paygo_base_url=zai_paygo_base_url,
            zai_coding_base_url=zai_coding_base_url,
            zai_base_url=zai_base_url,
            ollama_base_url=os.getenv("OPENPLANTER_OLLAMA_BASE_URL", "http://localhost:11434/v1"),
            exa_base_url=os.getenv("OPENPLANTER_EXA_BASE_URL", "https://api.exa.ai"),
            firecrawl_base_url=os.getenv("OPENPLANTER_FIRECRAWL_BASE_URL", "https://api.firecrawl.dev/v1"),
            openai_api_key=openai_api_key,
            anthropic_api_key=anthropic_api_key,
            openrouter_api_key=openrouter_api_key,
            cerebras_api_key=cerebras_api_key,
            zai_api_key=zai_api_key,
            exa_api_key=exa_api_key,
            firecrawl_api_key=firecrawl_api_key,
            web_search_provider=web_search_provider,
            voyage_api_key=voyage_api_key,
            max_depth=int(os.getenv("OPENPLANTER_MAX_DEPTH", "4")),
            max_steps_per_call=int(os.getenv("OPENPLANTER_MAX_STEPS", "100")),
            max_observation_chars=int(os.getenv("OPENPLANTER_MAX_OBS_CHARS", "6000")),
            command_timeout_sec=int(os.getenv("OPENPLANTER_CMD_TIMEOUT", "45")),
            shell=os.getenv("OPENPLANTER_SHELL", "/bin/sh"),
            max_files_listed=int(os.getenv("OPENPLANTER_MAX_FILES", "400")),
            max_file_chars=int(os.getenv("OPENPLANTER_MAX_FILE_CHARS", "20000")),
            max_search_hits=int(os.getenv("OPENPLANTER_MAX_SEARCH_HITS", "200")),
            max_shell_output_chars=int(os.getenv("OPENPLANTER_MAX_SHELL_CHARS", "16000")),
            session_root_dir=os.getenv("OPENPLANTER_SESSION_DIR", ".openplanter"),
            max_persisted_observations=int(os.getenv("OPENPLANTER_MAX_PERSISTED_OBS", "400")),
            max_solve_seconds=int(os.getenv("OPENPLANTER_MAX_SOLVE_SECONDS", "0")),
            rate_limit_max_retries=int(os.getenv("OPENPLANTER_RATE_LIMIT_MAX_RETRIES", "12")),
            zai_stream_max_retries=int(os.getenv("OPENPLANTER_ZAI_STREAM_MAX_RETRIES", "10")),
            rate_limit_backoff_base_sec=float(os.getenv("OPENPLANTER_RATE_LIMIT_BACKOFF_BASE_SEC", "1.0")),
            rate_limit_backoff_max_sec=float(os.getenv("OPENPLANTER_RATE_LIMIT_BACKOFF_MAX_SEC", "60.0")),
            rate_limit_retry_after_cap_sec=float(os.getenv("OPENPLANTER_RATE_LIMIT_RETRY_AFTER_CAP_SEC", "120.0")),
            recursive=os.getenv("OPENPLANTER_RECURSIVE", "true").strip().lower() in ("1", "true", "yes"),
            min_subtask_depth=int(os.getenv("OPENPLANTER_MIN_SUBTASK_DEPTH", "0")),
            acceptance_criteria=os.getenv("OPENPLANTER_ACCEPTANCE_CRITERIA", "true").strip().lower() in ("1", "true", "yes"),
            max_plan_chars=int(os.getenv("OPENPLANTER_MAX_PLAN_CHARS", "40000")),
            max_turn_summaries=int(os.getenv("OPENPLANTER_MAX_TURN_SUMMARIES", "50")),
            demo=os.getenv("OPENPLANTER_DEMO", "").strip().lower() in ("1", "true", "yes"),
        )
