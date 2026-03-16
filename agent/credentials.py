from __future__ import annotations

import getpass
import json
import os
import stat
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class CredentialBundle:
    openai_api_key: str | None = None
    openai_oauth_token: str | None = None
    anthropic_api_key: str | None = None
    openrouter_api_key: str | None = None
    cerebras_api_key: str | None = None
    zai_api_key: str | None = None
    exa_api_key: str | None = None
    firecrawl_api_key: str | None = None
    brave_api_key: str | None = None
    tavily_api_key: str | None = None
    voyage_api_key: str | None = None
    mistral_transcription_api_key: str | None = None

    def has_any(self) -> bool:
        return bool(
            (self.openai_api_key and self.openai_api_key.strip())
            or (self.openai_oauth_token and self.openai_oauth_token.strip())
            or (self.anthropic_api_key and self.anthropic_api_key.strip())
            or (self.openrouter_api_key and self.openrouter_api_key.strip())
            or (self.cerebras_api_key and self.cerebras_api_key.strip())
            or (self.zai_api_key and self.zai_api_key.strip())
            or (self.exa_api_key and self.exa_api_key.strip())
            or (self.firecrawl_api_key and self.firecrawl_api_key.strip())
            or (self.brave_api_key and self.brave_api_key.strip())
            or (self.tavily_api_key and self.tavily_api_key.strip())
            or (self.voyage_api_key and self.voyage_api_key.strip())
            or (
                self.mistral_transcription_api_key
                and self.mistral_transcription_api_key.strip()
            )
        )

    def merge_missing(self, other: "CredentialBundle") -> None:
        if not self.openai_api_key and other.openai_api_key:
            self.openai_api_key = other.openai_api_key
        if not self.openai_oauth_token and other.openai_oauth_token:
            self.openai_oauth_token = other.openai_oauth_token
        if not self.anthropic_api_key and other.anthropic_api_key:
            self.anthropic_api_key = other.anthropic_api_key
        if not self.openrouter_api_key and other.openrouter_api_key:
            self.openrouter_api_key = other.openrouter_api_key
        if not self.cerebras_api_key and other.cerebras_api_key:
            self.cerebras_api_key = other.cerebras_api_key
        if not self.zai_api_key and other.zai_api_key:
            self.zai_api_key = other.zai_api_key
        if not self.exa_api_key and other.exa_api_key:
            self.exa_api_key = other.exa_api_key
        if not self.firecrawl_api_key and other.firecrawl_api_key:
            self.firecrawl_api_key = other.firecrawl_api_key
        if not self.brave_api_key and other.brave_api_key:
            self.brave_api_key = other.brave_api_key
        if not self.tavily_api_key and other.tavily_api_key:
            self.tavily_api_key = other.tavily_api_key
        if not self.voyage_api_key and other.voyage_api_key:
            self.voyage_api_key = other.voyage_api_key
        if (
            not self.mistral_transcription_api_key
            and other.mistral_transcription_api_key
        ):
            self.mistral_transcription_api_key = other.mistral_transcription_api_key

    def to_json(self) -> dict[str, str]:
        out: dict[str, str] = {}
        if self.openai_api_key:
            out["openai_api_key"] = self.openai_api_key
        if self.openai_oauth_token:
            out["openai_oauth_token"] = self.openai_oauth_token
        if self.anthropic_api_key:
            out["anthropic_api_key"] = self.anthropic_api_key
        if self.openrouter_api_key:
            out["openrouter_api_key"] = self.openrouter_api_key
        if self.cerebras_api_key:
            out["cerebras_api_key"] = self.cerebras_api_key
        if self.zai_api_key:
            out["zai_api_key"] = self.zai_api_key
        if self.exa_api_key:
            out["exa_api_key"] = self.exa_api_key
        if self.firecrawl_api_key:
            out["firecrawl_api_key"] = self.firecrawl_api_key
        if self.brave_api_key:
            out["brave_api_key"] = self.brave_api_key
        if self.tavily_api_key:
            out["tavily_api_key"] = self.tavily_api_key
        if self.voyage_api_key:
            out["voyage_api_key"] = self.voyage_api_key
        if self.mistral_transcription_api_key:
            out["mistral_transcription_api_key"] = self.mistral_transcription_api_key
        return out

    @classmethod
    def from_json(cls, payload: dict[str, str] | None) -> "CredentialBundle":
        if not isinstance(payload, dict):
            return cls()
        return cls(
            openai_api_key=(payload.get("openai_api_key") or "").strip() or None,
            openai_oauth_token=(payload.get("openai_oauth_token") or "").strip() or None,
            anthropic_api_key=(payload.get("anthropic_api_key") or "").strip() or None,
            openrouter_api_key=(payload.get("openrouter_api_key") or "").strip() or None,
            cerebras_api_key=(payload.get("cerebras_api_key") or "").strip() or None,
            zai_api_key=(payload.get("zai_api_key") or "").strip() or None,
            exa_api_key=(payload.get("exa_api_key") or "").strip() or None,
            firecrawl_api_key=(payload.get("firecrawl_api_key") or "").strip() or None,
            brave_api_key=(payload.get("brave_api_key") or "").strip() or None,
            tavily_api_key=(payload.get("tavily_api_key") or "").strip() or None,
            voyage_api_key=(payload.get("voyage_api_key") or "").strip() or None,
            mistral_transcription_api_key=(
                payload.get("mistral_transcription_api_key") or ""
            ).strip()
            or None,
        )


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def parse_env_assignments(path: Path) -> dict[str, str]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {}

    env: dict[str, str] = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = _strip_quotes(value.strip())
        env[key] = value
    return env


def parse_env_file(path: Path) -> CredentialBundle:
    env = parse_env_assignments(path)
    return CredentialBundle(
        openai_api_key=(env.get("OPENAI_API_KEY") or env.get("OPENPLANTER_OPENAI_API_KEY") or "").strip() or None,
        openai_oauth_token=(
            env.get("OPENAI_OAUTH_TOKEN") or env.get("OPENPLANTER_OPENAI_OAUTH_TOKEN") or ""
        ).strip()
        or None,
        anthropic_api_key=(env.get("ANTHROPIC_API_KEY") or env.get("OPENPLANTER_ANTHROPIC_API_KEY") or "").strip()
        or None,
        openrouter_api_key=(env.get("OPENROUTER_API_KEY") or env.get("OPENPLANTER_OPENROUTER_API_KEY") or "").strip()
        or None,
        cerebras_api_key=(env.get("CEREBRAS_API_KEY") or env.get("OPENPLANTER_CEREBRAS_API_KEY") or "").strip()
        or None,
        zai_api_key=(env.get("ZAI_API_KEY") or env.get("OPENPLANTER_ZAI_API_KEY") or "").strip() or None,
        exa_api_key=(env.get("EXA_API_KEY") or env.get("OPENPLANTER_EXA_API_KEY") or "").strip() or None,
        firecrawl_api_key=(env.get("FIRECRAWL_API_KEY") or env.get("OPENPLANTER_FIRECRAWL_API_KEY") or "").strip()
        or None,
        brave_api_key=(env.get("BRAVE_API_KEY") or env.get("OPENPLANTER_BRAVE_API_KEY") or "").strip() or None,
        tavily_api_key=(env.get("TAVILY_API_KEY") or env.get("OPENPLANTER_TAVILY_API_KEY") or "").strip() or None,
        voyage_api_key=(env.get("VOYAGE_API_KEY") or env.get("OPENPLANTER_VOYAGE_API_KEY") or "").strip() or None,
        mistral_transcription_api_key=(
            env.get("OPENPLANTER_MISTRAL_TRANSCRIPTION_API_KEY")
            or env.get("MISTRAL_TRANSCRIPTION_API_KEY")
            or env.get("MISTRAL_API_KEY")
            or ""
        ).strip()
        or None,
    )


def credentials_from_env() -> CredentialBundle:
    return CredentialBundle(
        openai_api_key=(
            os.getenv("OPENPLANTER_OPENAI_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or ""
        ).strip()
        or None,
        openai_oauth_token=(
            os.getenv("OPENPLANTER_OPENAI_OAUTH_TOKEN") or os.getenv("OPENAI_OAUTH_TOKEN") or ""
        ).strip()
        or None,
        anthropic_api_key=(
            os.getenv("OPENPLANTER_ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_API_KEY") or ""
        ).strip()
        or None,
        openrouter_api_key=(
            os.getenv("OPENPLANTER_OPENROUTER_API_KEY") or os.getenv("OPENROUTER_API_KEY") or ""
        ).strip()
        or None,
        cerebras_api_key=(
            os.getenv("OPENPLANTER_CEREBRAS_API_KEY") or os.getenv("CEREBRAS_API_KEY") or ""
        ).strip()
        or None,
        zai_api_key=(
            os.getenv("OPENPLANTER_ZAI_API_KEY") or os.getenv("ZAI_API_KEY") or ""
        ).strip()
        or None,
        exa_api_key=(os.getenv("OPENPLANTER_EXA_API_KEY") or os.getenv("EXA_API_KEY") or "").strip() or None,
        firecrawl_api_key=(
            os.getenv("OPENPLANTER_FIRECRAWL_API_KEY") or os.getenv("FIRECRAWL_API_KEY") or ""
        ).strip()
        or None,
        brave_api_key=(os.getenv("OPENPLANTER_BRAVE_API_KEY") or os.getenv("BRAVE_API_KEY") or "").strip() or None,
        tavily_api_key=(os.getenv("OPENPLANTER_TAVILY_API_KEY") or os.getenv("TAVILY_API_KEY") or "").strip() or None,
        voyage_api_key=(os.getenv("OPENPLANTER_VOYAGE_API_KEY") or os.getenv("VOYAGE_API_KEY") or "").strip() or None,
        mistral_transcription_api_key=(
            os.getenv("OPENPLANTER_MISTRAL_TRANSCRIPTION_API_KEY")
            or os.getenv("MISTRAL_TRANSCRIPTION_API_KEY")
            or os.getenv("MISTRAL_API_KEY")
            or ""
        ).strip()
        or None,
    )


def discover_env_candidates(workspace: Path) -> list[Path]:
    ws = workspace.expanduser().resolve()
    current: Path | None = ws
    while current is not None:
        env_path = current / ".env"
        if env_path.exists():
            return [env_path]
        current = current.parent if current.parent != current else None
    return []


@dataclass(slots=True)
class CredentialStore:
    workspace: Path
    session_root_dir: str = ".openplanter"
    credentials_path: Path = field(init=False)

    def __post_init__(self) -> None:
        self.workspace = self.workspace.expanduser().resolve()
        root = self.workspace / self.session_root_dir
        self.credentials_path = root / "credentials.json"
        root.mkdir(parents=True, exist_ok=True)

    def load(self) -> CredentialBundle:
        if not self.credentials_path.exists():
            return CredentialBundle()
        try:
            payload = json.loads(self.credentials_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return CredentialBundle()
        return CredentialBundle.from_json(payload)

    def save(self, creds: CredentialBundle) -> None:
        payload = creds.to_json()
        self.credentials_path.parent.mkdir(parents=True, exist_ok=True)
        self.credentials_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        try:
            os.chmod(self.credentials_path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass


_USER_CONFIG_DIR = Path.home() / ".openplanter"


@dataclass(slots=True)
class UserCredentialStore:
    """User-level credential store at ~/.openplanter/credentials.json."""
    credentials_path: Path = field(init=False)

    def __post_init__(self) -> None:
        self.credentials_path = _USER_CONFIG_DIR / "credentials.json"

    def load(self) -> CredentialBundle:
        if not self.credentials_path.exists():
            return CredentialBundle()
        try:
            payload = json.loads(self.credentials_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return CredentialBundle()
        return CredentialBundle.from_json(payload)

    def save(self, creds: CredentialBundle) -> None:
        payload = creds.to_json()
        self.credentials_path.parent.mkdir(parents=True, exist_ok=True)
        self.credentials_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        try:
            os.chmod(self.credentials_path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass


def prompt_for_credentials(
    existing: CredentialBundle,
    force: bool = False,
) -> tuple[CredentialBundle, bool]:
    """Prompt user for credential input when interactive.

    Returns (updated_credentials, changed).
    """
    current = CredentialBundle(
        openai_api_key=existing.openai_api_key,
        openai_oauth_token=existing.openai_oauth_token,
        anthropic_api_key=existing.anthropic_api_key,
        openrouter_api_key=existing.openrouter_api_key,
        cerebras_api_key=existing.cerebras_api_key,
        zai_api_key=existing.zai_api_key,
        exa_api_key=existing.exa_api_key,
        firecrawl_api_key=existing.firecrawl_api_key,
        brave_api_key=existing.brave_api_key,
        tavily_api_key=existing.tavily_api_key,
        voyage_api_key=existing.voyage_api_key,
        mistral_transcription_api_key=existing.mistral_transcription_api_key,
    )

    should_prompt = force or not current.has_any()
    if not should_prompt:
        return current, False
    if not sys.stdin.isatty():
        return current, False

    if force:
        print("Key configuration mode: press Enter to keep existing values.")
    else:
        print("No API keys configured. Enter keys to enable providers (leave blank to skip).")

    changed = False

    def _ask(label: str, existing_value: str | None) -> str | None:
        nonlocal changed
        if force and existing_value:
            prompt = f"{label} API key [press Enter to keep existing]"
        else:
            prompt = f"{label} API key"
        value = getpass.getpass(prompt + ": ").strip()
        if not value:
            return existing_value
        changed = changed or (value != (existing_value or ""))
        return value

    current.openai_api_key = _ask("OpenAI", current.openai_api_key)
    current.openai_oauth_token = _ask("ChatGPT OAuth (Plus/Pro/Teams)", current.openai_oauth_token)
    current.anthropic_api_key = _ask("Anthropic", current.anthropic_api_key)
    current.openrouter_api_key = _ask("OpenRouter", current.openrouter_api_key)
    current.cerebras_api_key = _ask("Cerebras", current.cerebras_api_key)
    current.zai_api_key = _ask("Z.AI", current.zai_api_key)
    current.exa_api_key = _ask("Exa", current.exa_api_key)
    current.firecrawl_api_key = _ask("Firecrawl", current.firecrawl_api_key)
    current.brave_api_key = _ask("Brave", current.brave_api_key)
    current.tavily_api_key = _ask("Tavily", current.tavily_api_key)
    current.voyage_api_key = _ask("Voyage", current.voyage_api_key)
    current.mistral_transcription_api_key = _ask(
        "Mistral Transcription", current.mistral_transcription_api_key
    )
    if not force and current.has_any() and not existing.has_any():
        changed = True
    return current, changed
