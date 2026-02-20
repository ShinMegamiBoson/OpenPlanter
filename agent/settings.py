from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


VALID_REASONING_EFFORTS: set[str] = {"low", "medium", "high"}


def normalize_reasoning_effort(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().lower()
    if not cleaned:
        return None
    if cleaned not in VALID_REASONING_EFFORTS:
        raise ValueError(
            f"Invalid reasoning effort '{value}'. Expected one of: "
            f"{', '.join(sorted(VALID_REASONING_EFFORTS))}"
        )
    return cleaned


@dataclass(slots=True)
class PersistentSettings:
    default_model: str | None = None
    default_reasoning_effort: str | None = None
    default_model_openai: str | None = None
    default_model_anthropic: str | None = None
    default_model_openrouter: str | None = None
    default_model_cerebras: str | None = None
    default_model_zai: str | None = None

    def default_model_for_provider(self, provider: str) -> str | None:
        per_provider = {
            "openai": self.default_model_openai,
            "anthropic": self.default_model_anthropic,
            "openrouter": self.default_model_openrouter,
            "cerebras": self.default_model_cerebras,
            "zai": self.default_model_zai,
        }
        specific = per_provider.get(provider)
        if specific:
            return specific
        return self.default_model or None

    def normalized(self) -> "PersistentSettings":
        model = (self.default_model or "").strip() or None
        effort = normalize_reasoning_effort(self.default_reasoning_effort)
        return PersistentSettings(
            default_model=model,
            default_reasoning_effort=effort,
            default_model_openai=(self.default_model_openai or "").strip() or None,
            default_model_anthropic=(self.default_model_anthropic or "").strip() or None,
            default_model_openrouter=(self.default_model_openrouter or "").strip() or None,
            default_model_cerebras=(self.default_model_cerebras or "").strip() or None,
            default_model_zai=(self.default_model_zai or "").strip() or None,
        )

    def to_json(self) -> dict[str, str]:
        payload: dict[str, str] = {}
        if self.default_model:
            payload["default_model"] = self.default_model
        if self.default_reasoning_effort:
            payload["default_reasoning_effort"] = self.default_reasoning_effort
        if self.default_model_openai:
            payload["default_model_openai"] = self.default_model_openai
        if self.default_model_anthropic:
            payload["default_model_anthropic"] = self.default_model_anthropic
        if self.default_model_openrouter:
            payload["default_model_openrouter"] = self.default_model_openrouter
        if self.default_model_cerebras:
            payload["default_model_cerebras"] = self.default_model_cerebras
        if self.default_model_zai:
            payload["default_model_zai"] = self.default_model_zai
        return payload

    @classmethod
    def from_json(cls, payload: dict | None) -> "PersistentSettings":
        if not isinstance(payload, dict):
            return cls()
        return cls(
            default_model=(str(payload.get("default_model", "")).strip() or None),
            default_reasoning_effort=(
                str(payload.get("default_reasoning_effort", "")).strip() or None
            ),
            default_model_openai=(str(payload.get("default_model_openai", "")).strip() or None),
            default_model_anthropic=(str(payload.get("default_model_anthropic", "")).strip() or None),
            default_model_openrouter=(str(payload.get("default_model_openrouter", "")).strip() or None),
            default_model_cerebras=(str(payload.get("default_model_cerebras", "")).strip() or None),
            default_model_zai=(str(payload.get("default_model_zai", "")).strip() or None),
        ).normalized()


@dataclass(slots=True)
class SettingsStore:
    workspace: Path
    session_root_dir: str = ".openplanter"
    settings_path: Path = field(init=False)

    def __post_init__(self) -> None:
        self.workspace = self.workspace.expanduser().resolve()
        root = self.workspace / self.session_root_dir
        root.mkdir(parents=True, exist_ok=True)
        self.settings_path = root / "settings.json"

    def load(self) -> PersistentSettings:
        if not self.settings_path.exists():
            return PersistentSettings()
        try:
            parsed = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return PersistentSettings()
        return PersistentSettings.from_json(parsed)

    def save(self, settings: PersistentSettings) -> None:
        normalized = settings.normalized()
        self.settings_path.write_text(
            json.dumps(normalized.to_json(), indent=2),
            encoding="utf-8",
        )
