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
    anthropic_api_key: str | None = None
    openrouter_api_key: str | None = None
    cerebras_api_key: str | None = None
    exa_api_key: str | None = None
    voyage_api_key: str | None = None
    gemini_api_key: str | None = None

    def has_any(self) -> bool:
        return bool(
            (self.openai_api_key and self.openai_api_key.strip())
            or (self.anthropic_api_key and self.anthropic_api_key.strip())
            or (self.openrouter_api_key and self.openrouter_api_key.strip())
            or (self.cerebras_api_key and self.cerebras_api_key.strip())
            or (self.exa_api_key and self.exa_api_key.strip())
            or (self.voyage_api_key and self.voyage_api_key.strip())
            or (self.gemini_api_key and self.gemini_api_key.strip())
        )

    def merge_missing(self, other: CredentialBundle) -> None:
        if not self.openai_api_key and other.openai_api_key:
            self.openai_api_key = other.openai_api_key
        if not self.anthropic_api_key and other.anthropic_api_key:
            self.anthropic_api_key = other.anthropic_api_key
        if not self.openrouter_api_key and other.openrouter_api_key:
            self.openrouter_api_key = other.openrouter_api_key
        if not self.cerebras_api_key and other.cerebras_api_key:
            self.cerebras_api_key = other.cerebras_api_key
        if not self.exa_api_key and other.exa_api_key:
            self.exa_api_key = other.exa_api_key
        if not self.voyage_api_key and other.voyage_api_key:
            self.voyage_api_key = other.voyage_api_key
        if not self.gemini_api_key and other.gemini_api_key:
            self.gemini_api_key = other.gemini_api_key

    def to_json(self) -> dict[str, str]:
        out: dict[str, str] = {}
        if self.openai_api_key:
            out["openai_api_key"] = self.openai_api_key
        if self.anthropic_api_key:
            out["anthropic_api_key"] = self.anthropic_api_key
        if self.openrouter_api_key:
            out["openrouter_api_key"] = self.openrouter_api_key
        if self.cerebras_api_key:
            out["cerebras_api_key"] = self.cerebras_api_key
        if self.exa_api_key:
            out["exa_api_key"] = self.exa_api_key
        if self.voyage_api_key:
            out["voyage_api_key"] = self.voyage_api_key
        if self.gemini_api_key:
            out["gemini_api_key"] = self.gemini_api_key
        return out

    @classmethod
    def from_json(cls, payload: dict[str, str] | None) -> CredentialBundle:
        if not isinstance(payload, dict):
            return cls()
        return cls(
            openai_api_key=(payload.get("openai_api_key") or "").strip() or None,
            anthropic_api_key=(payload.get("anthropic_api_key") or "").strip() or None,
            openrouter_api_key=(payload.get("openrouter_api_key") or "").strip() or None,
            cerebras_api_key=(payload.get("cerebras_api_key") or "").strip() or None,
            exa_api_key=(payload.get("exa_api_key") or "").strip() or None,
            voyage_api_key=(payload.get("voyage_api_key") or "").strip() or None,
            gemini_api_key=(payload.get("gemini_api_key") or "").strip() or None,
        )


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def parse_env_file(path: Path) -> CredentialBundle:
    if not path.exists() or not path.is_file():
        return CredentialBundle()
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return CredentialBundle()

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

    return CredentialBundle(
        openai_api_key=(env.get("OPENAI_API_KEY") or env.get("OPENPLANTER_OPENAI_API_KEY") or "").strip() or None,
        anthropic_api_key=(env.get("ANTHROPIC_API_KEY") or env.get("OPENPLANTER_ANTHROPIC_API_KEY") or "").strip()
        or None,
        openrouter_api_key=(env.get("OPENROUTER_API_KEY") or env.get("OPENPLANTER_OPENROUTER_API_KEY") or "").strip()
        or None,
        cerebras_api_key=(env.get("CEREBRAS_API_KEY") or env.get("OPENPLANTER_CEREBRAS_API_KEY") or "").strip()
        or None,
        exa_api_key=(env.get("EXA_API_KEY") or env.get("OPENPLANTER_EXA_API_KEY") or "").strip() or None,
        voyage_api_key=(env.get("VOYAGE_API_KEY") or env.get("OPENPLANTER_VOYAGE_API_KEY") or "").strip() or None,
        gemini_api_key=(env.get("OPENPLANTER_GEMINI_API_KEY") or env.get("GEMINI_API_KEY") or env.get("GOOGLE_API_KEY") or "").strip() or None,
    )


def credentials_from_env() -> CredentialBundle:
    return CredentialBundle(
        openai_api_key=(
            os.getenv("OPENPLANTER_OPENAI_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or ""
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
        exa_api_key=(os.getenv("OPENPLANTER_EXA_API_KEY") or os.getenv("EXA_API_KEY") or "").strip() or None,
        voyage_api_key=(os.getenv("OPENPLANTER_VOYAGE_API_KEY") or os.getenv("VOYAGE_API_KEY") or "").strip() or None,
        gemini_api_key=(
            os.getenv("OPENPLANTER_GEMINI_API_KEY")
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
            or ""
        ).strip() or None,
    )


def discover_env_candidates(workspace: Path) -> list[Path]:
    ws = workspace.expanduser().resolve()
    candidates: list[Path] = [
        ws / ".env",
    ]
    seen: set[str] = set()
    unique: list[Path] = []
    for path in candidates:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


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
        anthropic_api_key=existing.anthropic_api_key,
        openrouter_api_key=existing.openrouter_api_key,
        cerebras_api_key=existing.cerebras_api_key,
        exa_api_key=existing.exa_api_key,
        voyage_api_key=existing.voyage_api_key,
        gemini_api_key=existing.gemini_api_key,
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
    current.anthropic_api_key = _ask("Anthropic", current.anthropic_api_key)
    current.openrouter_api_key = _ask("OpenRouter", current.openrouter_api_key)
    current.cerebras_api_key = _ask("Cerebras", current.cerebras_api_key)
    current.exa_api_key = _ask("Exa", current.exa_api_key)
    current.voyage_api_key = _ask("Voyage", current.voyage_api_key)
    current.gemini_api_key = _ask("Gemini", current.gemini_api_key)
    if not force and current.has_any() and not existing.has_any():
        changed = True
    return current, changed
