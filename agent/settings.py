from __future__ import annotations

import base64
import json
import os
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


VALID_REASONING_EFFORTS: set[str] = {"low", "medium", "high"}


# Sentinel used in settings.json to mark which fields were encrypted at rest.
_ENCRYPTED_FIELDS_KEY = "_encrypted_fields"


def _master_password() -> str | None:
    return os.getenv("OPENPLANTER_MASTER_PASSWORD", "").strip() or None


def _fernet_key(password: str) -> bytes:
    """Derive a Fernet-compatible key from a user-supplied password."""
    # Fernet keys are 32 bytes encoded with URL-safe base64.  We derive them
    # with PBKDF2-HMAC-SHA256 so the password is not stored on disk.
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"openplanter-settings-v1",
        iterations=100_000,
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


def _encrypt_value(plaintext: str, password: str) -> str:
    from cryptography.fernet import Fernet

    return Fernet(_fernet_key(password)).encrypt(plaintext.encode("utf-8")).decode("utf-8")


def _decrypt_value(ciphertext: str, password: str) -> str:
    from cryptography.fernet import Fernet

    return Fernet(_fernet_key(password)).decrypt(ciphertext.encode("utf-8")).decode("utf-8")


def _encrypt_sensitive_fields(payload: dict[str, Any], password: str) -> dict[str, Any]:
    encrypted = set()
    out = dict(payload)
    for key in ("crowd_nsec", "crowd_private_nsec"):
        value = out.get(key)
        if value:
            out[key] = _encrypt_value(value, password)
            encrypted.add(key)
    if encrypted:
        out[_ENCRYPTED_FIELDS_KEY] = sorted(encrypted)
    return out


def _decrypt_sensitive_fields(
    payload: dict[str, Any], password: str | None
) -> dict[str, Any]:
    encrypted = payload.pop(_ENCRYPTED_FIELDS_KEY, [])
    if not isinstance(encrypted, list):
        encrypted = []
    out = dict(payload)
    if encrypted and not password:
        warnings.warn(
            "Settings file contains encrypted fields but OPENPLANTER_MASTER_PASSWORD is not set; "
            "crowd identity keys cannot be loaded.",
            stacklevel=2,
        )
        for key in encrypted:
            out.pop(key, None)
        return out
    for key in encrypted:
        value = out.get(key)
        if value and password:
            try:
                out[key] = _decrypt_value(value, password)
            except Exception:
                warnings.warn(
                    f"Could not decrypt settings field {key}; using defaults.",
                    stacklevel=2,
                )
                out.pop(key, None)
    return out


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
    default_model_ollama: str | None = None
    crowd_relays: list[str] = field(default_factory=list)
    crowd_nsec: str | None = None
    crowd_private_relays: list[str] = field(default_factory=list)
    crowd_private_nsec: str | None = None
    crowd_worker_tags: list[str] = field(default_factory=list)
    crowd_epsilon: float = 1.0

    def default_model_for_provider(self, provider: str) -> str | None:
        per_provider = {
            "openai": self.default_model_openai,
            "anthropic": self.default_model_anthropic,
            "openrouter": self.default_model_openrouter,
            "cerebras": self.default_model_cerebras,
            "ollama": self.default_model_ollama,
        }
        specific = per_provider.get(provider)
        if specific:
            return specific
        return self.default_model or None

    def normalized(self) -> "PersistentSettings":
        model = (self.default_model or "").strip() or None
        effort = normalize_reasoning_effort(self.default_reasoning_effort)
        relays = list(self.crowd_relays) if self.crowd_relays else []
        private_relays = list(self.crowd_private_relays) if self.crowd_private_relays else []
        worker_tags = list(self.crowd_worker_tags) if self.crowd_worker_tags else []
        return PersistentSettings(
            default_model=model,
            default_reasoning_effort=effort,
            default_model_openai=(self.default_model_openai or "").strip() or None,
            default_model_anthropic=(self.default_model_anthropic or "").strip() or None,
            default_model_openrouter=(self.default_model_openrouter or "").strip() or None,
            default_model_cerebras=(self.default_model_cerebras or "").strip() or None,
            default_model_ollama=(self.default_model_ollama or "").strip() or None,
            crowd_relays=relays,
            crowd_nsec=(self.crowd_nsec or "").strip() or None,
            crowd_private_relays=private_relays,
            crowd_private_nsec=(self.crowd_private_nsec or "").strip() or None,
            crowd_worker_tags=worker_tags,
            crowd_epsilon=self.crowd_epsilon if self.crowd_epsilon is not None else 1.0,
        )

    def to_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
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
        if self.default_model_ollama:
            payload["default_model_ollama"] = self.default_model_ollama
        if self.crowd_relays:
            payload["crowd_relays"] = self.crowd_relays
        if self.crowd_nsec:
            payload["crowd_nsec"] = self.crowd_nsec
        if self.crowd_private_relays:
            payload["crowd_private_relays"] = self.crowd_private_relays
        if self.crowd_private_nsec:
            payload["crowd_private_nsec"] = self.crowd_private_nsec
        if self.crowd_worker_tags:
            payload["crowd_worker_tags"] = self.crowd_worker_tags
        if self.crowd_epsilon is not None:
            payload["crowd_epsilon"] = self.crowd_epsilon
        return payload

    @classmethod
    def from_json(cls, payload: dict | None) -> "PersistentSettings":
        if not isinstance(payload, dict):
            return cls()
        relays = payload.get("crowd_relays", [])
        private_relays = payload.get("crowd_private_relays", [])
        worker_tags = payload.get("crowd_worker_tags", [])
        epsilon = payload.get("crowd_epsilon", 1.0)
        return cls(
            default_model=(str(payload.get("default_model", "")).strip() or None),
            default_reasoning_effort=(
                str(payload.get("default_reasoning_effort", "")).strip() or None
            ),
            default_model_openai=(str(payload.get("default_model_openai", "")).strip() or None),
            default_model_anthropic=(str(payload.get("default_model_anthropic", "")).strip() or None),
            default_model_openrouter=(str(payload.get("default_model_openrouter", "")).strip() or None),
            default_model_cerebras=(str(payload.get("default_model_cerebras", "")).strip() or None),
            default_model_ollama=(str(payload.get("default_model_ollama", "")).strip() or None),
            crowd_relays=relays if isinstance(relays, list) else [],
            crowd_nsec=(str(payload.get("crowd_nsec", "")).strip() or None),
            crowd_private_relays=private_relays if isinstance(private_relays, list) else [],
            crowd_private_nsec=(str(payload.get("crowd_private_nsec", "")).strip() or None),
            crowd_worker_tags=worker_tags if isinstance(worker_tags, list) else [],
            crowd_epsilon=float(epsilon) if epsilon is not None else 1.0,
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
        # Restrict workspace metadata so secret keys are readable only by the owner.
        try:
            os.chmod(root, 0o700)
        except OSError:
            pass
        self.settings_path = root / "settings.json"

    def load(self) -> PersistentSettings:
        if not self.settings_path.exists():
            return PersistentSettings()
        try:
            parsed = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return PersistentSettings()
        parsed = _decrypt_sensitive_fields(parsed, _master_password())
        return PersistentSettings.from_json(parsed)

    def save(self, settings: PersistentSettings) -> None:
        normalized = settings.normalized()
        payload = normalized.to_json()
        password = _master_password()
        if password:
            payload = _encrypt_sensitive_fields(payload, password)
        else:
            # If the on-disk settings were previously encrypted and no password
            # is available, preserve the encrypted identity keys rather than
            # overwriting them with a newly-generated plaintext key.
            existing: dict[str, Any] | None = None
            if self.settings_path.exists():
                try:
                    existing = json.loads(self.settings_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    existing = None
            encrypted_keys = (
                existing.get(_ENCRYPTED_FIELDS_KEY, [])
                if isinstance(existing, dict)
                else []
            )
            if encrypted_keys:
                warnings.warn(
                    "Settings file contains encrypted identity keys; "
                    "set OPENPLANTER_MASTER_PASSWORD to load them. "
                    "Plaintext identity keys will not be written.",
                    stacklevel=2,
                )
                for key in encrypted_keys:
                    if existing and key in existing:
                        payload[key] = existing[key]
                payload[_ENCRYPTED_FIELDS_KEY] = list(encrypted_keys)
        self.settings_path.write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )
        try:
            os.chmod(self.settings_path, 0o600)
        except OSError:
            pass
