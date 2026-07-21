"""OpenPlanter Crowd — local Nostr-compatible task market scaffolding.

Provides the local storage, identity, event model, and in-process relay
plumbing described in the OpenPlanter Crowd design document. This is a
Phase 0/1 foundation: storage, task hashes, local publish/subscribe, and a
strfry wrapper for later federation.

Event signing uses coincurve's BIP-340 Schnorr implementation. If coincurve is
not installed, it falls back to an HMAC-SHA256 placeholder that is only valid
for the in-memory relay.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
import random
import re
import secrets
import shutil
import signal
import subprocess
import threading
import time
import traceback
import warnings
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from .config import AgentConfig

try:
    from filelock import FileLock, Timeout as _FileLockTimeout
except Exception:  # pragma: no cover - filelock optional fallback
    FileLock = None  # type: ignore[misc,assignment]
    _FileLockTimeout = Exception

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives import hashes
    HAS_CRYPTOGRAPHY = True
except Exception:  # pragma: no cover - encryption optional fallback
    AESGCM = None  # type: ignore[misc,assignment]
    HKDF = None  # type: ignore[misc,assignment]
    hashes = None  # type: ignore[misc,assignment]
    HAS_CRYPTOGRAPHY = False

try:
    from .relay import RelayPool, NostrRelayConnection
except Exception:  # pragma: no cover - websockets optional fallback
    RelayPool = None  # type: ignore[misc,assignment]
    NostrRelayConnection = None  # type: ignore[misc,assignment]

try:
    from .relay_server import CrowdRelayServer
except Exception:  # pragma: no cover - websockets optional fallback
    CrowdRelayServer = None  # type: ignore[misc,assignment]

CROWD_KIND_TASK = 31001
CROWD_KIND_CLAIM = 31002
CROWD_KIND_RESULT = 31003
CROWD_KIND_AVAILABLE = 31004
CROWD_KIND_EMBEDDING = 31005
CROWD_KIND_CANCEL = 31006
CROWD_KIND_FEEDBACK = 31007

NOSTR_KIND_METADATA = 0
NOSTR_KIND_RELAY_LIST = 10002
NOSTR_KIND_CONTACT_LIST = 30000


class CrowdError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _unix_now() -> int:
    return int(time.time())


def _safe_component(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-") or "artifact"


def _normalize(text: str) -> str:
    return " ".join(text.split()).lower()


def _task_hash(
    objective: str,
    acceptance_criteria: str,
    context_hash: str,
    tags: list[str],
) -> str:
    body = json.dumps(
        {
            "objective": _normalize(objective),
            "acceptance_criteria": _normalize(acceptance_criteria),
            "context_hash": context_hash,
            "tags": sorted((t.lower() for t in tags)),
        },
        sort_keys=True,
        ensure_ascii=True,
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _xonly_to_pubkey_bytes(xonly_hex: str) -> bytes:
    """Convert a NIP-01 x-only pubkey hex to a compressed secp256k1 point.

    NIP-01 x-only keys use the even-y point, so ``02 || xonly`` is canonical.
    """
    raw = bytes.fromhex(xonly_hex[:64])
    try:
        from coincurve import PublicKey

        return PublicKey(b"\x02" + raw).format()
    except Exception:
        return b"\x02" + raw


def _derive_aes_key(shared_secret: bytes) -> bytes:
    """Derive a 32-byte AES key from an ECDH shared secret using HKDF-SHA256."""
    if AESGCM is None or HKDF is None or hashes is None:
        raise CrowdError("cryptography library required for private tasks")
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"openplanter-private-brief",
    ).derive(shared_secret)


def _encrypt_brief(brief: str, sender_priv_hex: str, recipient_xonlys: list[str]) -> dict[str, Any]:
    """Encrypt a brief for a list of NIP-01 x-only recipient public keys.

    Returns a dict with one encrypted item per recipient.  Recipients can try
    each item and decrypt the one intended for them using their own private key.
    """
    if not HAS_CRYPTOGRAPHY:
        raise CrowdError("cryptography not installed")
    from coincurve import PrivateKey, PublicKey

    sender_sk = PrivateKey.from_hex(sender_priv_hex.strip().lower())
    items: list[dict[str, str]] = []
    brief_bytes = brief.encode("utf-8")
    for r in recipient_xonlys:
        recipient_pub = PublicKey(_xonly_to_pubkey_bytes(r))
        ephemeral = PrivateKey()
        ephemeral_pub = ephemeral.public_key.format()
        shared = ephemeral.ecdh(recipient_pub.format())
        key = _derive_aes_key(shared)
        nonce = os.urandom(12)
        ct = AESGCM(key).encrypt(nonce, brief_bytes, None)
        items.append(
            {
                "ephemeral_pub": ephemeral_pub.hex(),
                "nonce": nonce.hex(),
                "ciphertext": ct.hex(),
            }
        )
    return {"version": 1, "items": items}


def _bip340_secret_hex(private_hex: str) -> str:
    """Return the BIP-340 secret scalar that corresponds to an x-only pubkey.

    Coincurve private keys map to public points that can have odd or even y.
    BIP-340 public keys are the x-coordinate with even-y lift, so the secret
    for an odd-y private key is ``n - d``.
    """
    from coincurve import PrivateKey
    from coincurve.utils import GROUP_ORDER_INT

    sk = PrivateKey.from_hex(private_hex.strip().lower())
    if sk.public_key.format()[0] == 0x02:
        return private_hex.strip().lower()
    d = sk.to_int()
    d_prime = (GROUP_ORDER_INT - d) % GROUP_ORDER_INT
    return PrivateKey.from_int(d_prime).to_hex()


def _decrypt_brief(encrypted: dict[str, Any], private_hex: str) -> str | None:
    """Try to decrypt any item of an encrypted brief with the given private key."""
    if not HAS_CRYPTOGRAPHY:
        return None
    from coincurve import PrivateKey

    sk = PrivateKey.from_hex(_bip340_secret_hex(private_hex))
    for item in encrypted.get("items", []):
        try:
            ephemeral_pub = bytes.fromhex(item["ephemeral_pub"])
            shared = sk.ecdh(ephemeral_pub)
            key = _derive_aes_key(shared)
            nonce = bytes.fromhex(item["nonce"])
            ct = bytes.fromhex(item["ciphertext"])
            plain = AESGCM(key).decrypt(nonce, ct, None)
            return plain.decode("utf-8")
        except Exception:
            continue
    return None


def _sanitize_context(context: dict[str, Any]) -> dict[str, Any]:
    """Return a privacy-safe view of a context bundle.

    Keys known to contain sensitive literals (credentials, raw data, files) are
    replaced by type hints or hashes.  The sanitized bundle can be used as a
    public task context hash without leaking the underlying content.
    """
    if not isinstance(context, dict):
        return {"hint": str(context)[:80]}
    sanitized: dict[str, Any] = {}
    secret_keys = {"api_key", "api_keys", "token", "tokens", "secret", "password", "credentials", "authorization"}
    for key, value in context.items():
        k_lower = str(key).lower()
        if k_lower in secret_keys:
            sanitized[key] = "<redacted>"
        elif isinstance(value, (dict, list, tuple)):
            # For nested structures, summarize lengths and recurse one level for dicts.
            if isinstance(value, dict):
                sanitized[key] = {k: "<redacted>" if str(k).lower() in secret_keys else f"<{type(v).__name__} len={len(str(v))}>" for k, v in value.items()}
            else:
                sanitized[key] = f"<list len={len(value)}>"
        elif isinstance(value, (str, bytes)) and len(str_value := str(value)) > 200:
            sanitized[key] = str_value[:200] + "..."
        else:
            sanitized[key] = value
    return sanitized


def _event_id(event: dict[str, Any]) -> str:
    """NIP-01 event id: sha256 of [0,pubkey,created_at,kind,tags,content]."""
    normed = [
        0,
        event["pubkey"],
        event["created_at"],
        event["kind"],
        event["tags"],
        event["content"],
    ]
    serialized = json.dumps(normed, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _can_schnorr_verify() -> bool:
    """Return True if coincurve BIP-340 Schnorr verification is available."""
    try:
        from coincurve import PublicKeyXOnly  # noqa: F401
        return True
    except Exception:  # pragma: no cover - coincurve optional
        return False


def verify_event(event: NostrEvent) -> bool:
    """Verify a Nostr event's id and BIP-340 Schnorr signature.

    Returns True if the event id matches NIP-01 serialization and the
    signature is valid for the claimed public key. Returns False for HMAC
    placeholder events when coincurve is unavailable.
    """
    try:
        expected = _event_id(event.to_unsigned_dict())
        if event.id != expected:
            return False
        if len(event.pubkey) != 64 or len(event.sig) != 128:
            return False
        if not _can_schnorr_verify():
            return False
        from coincurve import PublicKeyXOnly

        pubkey = bytes.fromhex(event.pubkey)
        sig = bytes.fromhex(event.sig)
        digest = bytes.fromhex(event.id)
        return bool(PublicKeyXOnly(pubkey).verify(sig, digest))
    except Exception:  # pragma: no cover - malformed hex/key
        return False


@dataclass
class NostrEvent:
    pubkey: str
    created_at: int
    kind: int
    tags: list[list[str]]
    content: str
    id: str = ""
    sig: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id or _event_id(self.to_unsigned_dict()),
            "pubkey": self.pubkey,
            "created_at": self.created_at,
            "kind": self.kind,
            "tags": self.tags,
            "content": self.content,
            "sig": self.sig,
        }

    def to_unsigned_dict(self) -> dict[str, Any]:
        return {
            "pubkey": self.pubkey,
            "created_at": self.created_at,
            "kind": self.kind,
            "tags": self.tags,
            "content": self.content,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NostrEvent":
        return cls(
            pubkey=data.get("pubkey", ""),
            created_at=data.get("created_at", 0),
            kind=data.get("kind", 0),
            tags=data.get("tags", []),
            content=data.get("content", ""),
            id=data.get("id", ""),
            sig=data.get("sig", ""),
        )


def _hex_to_bytes(value: str) -> bytes:
    if len(value) == 64:
        return bytes.fromhex(value)
    # Bech32 nsec/npub decoding is out of scope for this scaffold.
    raise CrowdError("Expected 64-character hex key or npub/nsec bech32 support is not implemented")


class CrowdIdentity:
    """Local secp256k1 keypair for the OpenPlanter node.

    Generates a new key if *nsec_hex* is not supplied. The public key is the
    32-byte x-coordinate used by Nostr (hex). Signing uses BIP-340 Schnorr
    via coincurve when available.
    """

    def __init__(self, nsec_hex: str | None = None) -> None:
        try:
            from coincurve import PrivateKey

            if nsec_hex:
                self._priv = PrivateKey.from_hex(nsec_hex.strip().lower())
            else:
                self._priv = PrivateKey()
            self._pub = self._priv.public_key.format(compressed=False)[1:33]
            self._use_schnorr = True
        except ImportError:
            warnings.warn(
                "coincurve not installed; using local-only HMAC placeholder identity",
                stacklevel=2,
            )
            self._use_schnorr = False
            if nsec_hex:
                self._priv = _hex_to_bytes(nsec_hex.strip().lower())
            else:
                self._priv = secrets.token_bytes(32)
            self._pub = hashlib.sha256(self._priv).digest()

    @property
    def private_hex(self) -> str:
        if self._use_schnorr:
            return self._priv.to_hex()
        return self._priv.hex()

    @property
    def public_hex(self) -> str:
        return self._pub.hex()

    @property
    def nsec_hex(self) -> str:
        return self.private_hex

    @property
    def npub_hex(self) -> str:
        return self.public_hex

    def sign_event(self, event: NostrEvent) -> None:
        event.id = _event_id(event.to_unsigned_dict())
        if self._use_schnorr:
            aux = secrets.token_bytes(32)
            event.sig = self._priv.sign_schnorr(bytes.fromhex(event.id), aux).hex()
        else:
            event.sig = hmac.new(self._priv, event.id.encode("utf-8"), hashlib.sha256).hexdigest()

    def verify_event(self, event: NostrEvent) -> bool:
        """Verify the event id and signature were produced by this identity."""
        if event.pubkey != self.public_hex:
            return False
        return verify_event(event)


@dataclass
class CrowdTask:
    task_hash: str
    objective: str
    acceptance_criteria: str
    context_hash: str = ""
    parent_session_id: str | None = None
    parent_task_hash: str | None = None
    tags: list[str] = field(default_factory=list)
    stake: str = "low"
    required_tier: str | None = None
    deadline: str | None = None
    expires_at: str | None = None
    status: str = "open"
    created_at: str = field(default_factory=_utc_now)
    claimed_by: str | None = None
    claimed_at: str | None = None
    result_event_id: str | None = None
    merged: bool = False
    # Private-task support
    private: bool = False
    private_allowed: list[str] = field(default_factory=list)
    encrypted_brief: str | None = None
    # Nostr addressable-event identifiers for this task, written when published.
    event_id: str | None = None
    event_pubkey: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CrowdTask":
        return cls(**{k: v for k, v in data.items() if k in {f.name for f in cls.__dataclass_fields__.values()}})

    @classmethod
    def build(
        cls,
        objective: str,
        acceptance_criteria: str,
        context_hash: str = "",
        parent_session_id: str | None = None,
        parent_task_hash: str | None = None,
        tags: list[str] | None = None,
        stake: str = "low",
        required_tier: str | None = None,
        deadline: str | None = None,
        expires_at: str | None = None,
        private: bool = False,
        private_allowed: list[str] | None = None,
        encrypted_brief: str | None = None,
    ) -> "CrowdTask":
        tags = sorted({t.lower().strip() for t in (tags or []) if t.strip()})
        return cls(
            task_hash=_task_hash(objective, acceptance_criteria, context_hash, tags),
            objective=objective,
            acceptance_criteria=acceptance_criteria,
            context_hash=context_hash,
            parent_session_id=parent_session_id,
            parent_task_hash=parent_task_hash,
            tags=tags,
            stake=stake,
            required_tier=required_tier,
            deadline=deadline,
            expires_at=expires_at,
            status="open",
            private=private,
            private_allowed=list(private_allowed or []),
            encrypted_brief=encrypted_brief,
        )


class CrowdStore:
    """Local on-disk persistence for crowd tasks, trust lists, and worker profile."""

    def __init__(self, workspace: Path, session_root_dir: str = ".openplanter") -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        self.root = (self.workspace / session_root_dir / "crowd").resolve()
        self.tasks_dir = self.root / "tasks"
        self.events_dir = self.root / "events"
        self.trust_path = self.root / "trust.json"
        self.worker_profile_path = self.root / "worker_profile.json"
        self.vector_index_path = self.root / "vector_index.json"
        self._mutex = threading.Lock()
        self.lock_path = self.root / ".crowd.lock"
        self._file_lock = FileLock(str(self.lock_path), timeout=5) if FileLock is not None else None
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self.events_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.root, 0o700)
            os.chmod(self.tasks_dir, 0o700)
            os.chmod(self.events_dir, 0o700)
        except OSError:
            pass

    @contextmanager
    def locked(self):
        """Process- and thread-safe lock for all store mutations."""
        with self._mutex:
            if self._file_lock is None:
                yield
            else:
                try:
                    self._file_lock.acquire()
                except _FileLockTimeout as exc:
                    raise CrowdError("Timed out acquiring crowd store lock") from exc
                try:
                    yield
                finally:
                    try:
                        self._file_lock.release()
                    except Exception:
                        pass

    def _task_dir(self, task_hash: str) -> Path:
        return self.tasks_dir / task_hash

    def _metadata_path(self, task_hash: str) -> Path:
        return self._task_dir(task_hash) / "metadata.json"

    def _event_dir(self, task_hash: str) -> Path:
        return self.events_dir / task_hash

    def _event_path(self, task_hash: str, event_id: str) -> Path:
        return self._event_dir(task_hash) / f"{event_id}.json"

    def context_bundle_dir(self, task_hash: str) -> Path:
        path = self._task_dir(task_hash) / "context_bundle"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def work_dir(self, task_hash: str) -> Path:
        path = self._task_dir(task_hash) / "work"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def result_dir(self, task_hash: str) -> Path:
        path = self._task_dir(task_hash) / "result"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def create_task(
        self,
        task: CrowdTask,
        event: NostrEvent | None = None,
    ) -> CrowdTask:
        with self.locked():
            self._write_task(task)
            if event is not None:
                self._write_event(event, task.task_hash)
        return task

    def _write_task(self, task: CrowdTask) -> None:
        self._task_dir(task.task_hash).mkdir(parents=True, exist_ok=True)
        self._metadata_path(task.task_hash).write_text(
            json.dumps(task.to_dict(), indent=2, ensure_ascii=True),
            encoding="utf-8",
        )

    def get_task(self, task_hash: str) -> CrowdTask | None:
        path = self._metadata_path(task_hash)
        if not path.exists():
            return None
        try:
            return CrowdTask.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, TypeError):
            return None

    def list_tasks(
        self,
        status: str | None = None,
        tags: list[str] | None = None,
    ) -> list[CrowdTask]:
        tasks: list[CrowdTask] = []
        for p in self.tasks_dir.iterdir():
            if not p.is_dir():
                continue
            task = self.get_task(p.name)
            if task is None:
                continue
            if status and task.status != status:
                continue
            if tags and not any(t in task.tags for t in tags):
                continue
            tasks.append(task)
        return tasks

    def update_task(self, task_hash: str, **updates: Any) -> CrowdTask | None:
        with self.locked():
            task = self.get_task(task_hash)
            if task is None:
                return None
            for key, value in updates.items():
                if hasattr(task, key):
                    setattr(task, key, value)
            self._write_task(task)
            return task

    def cancel_task(
        self,
        task_hash: str,
        event: NostrEvent | None = None,
    ) -> CrowdTask | None:
        with self.locked():
            task = self.get_task(task_hash)
            if task is None or task.status in {"done", "merged", "canceled"}:
                return None
            task.status = "canceled"
            self._write_task(task)
            if event is not None:
                self._write_event(event, task_hash)
            return task

    def claim_task(
        self,
        task_hash: str,
        worker_pubkey: str,
        event: NostrEvent | None = None,
    ) -> CrowdTask | None:
        with self.locked():
            task = self.get_task(task_hash)
            if task is None or task.status != "open":
                return None
            task.status = "claimed"
            task.claimed_by = worker_pubkey
            task.claimed_at = _utc_now()
            self._write_task(task)
            if event is not None:
                self._write_event(event, task_hash)
            return task

    def write_result(
        self,
        task_hash: str,
        content: str,
        event: NostrEvent | None = None,
    ) -> CrowdTask | None:
        with self.locked():
            task = self.get_task(task_hash)
            if task is None or task.status != "claimed":
                return None
            rdir = self.result_dir(task_hash)
            (rdir / "result.md").write_text(content, encoding="utf-8")
            task.status = "done"
            task.result_event_id = event.id if event is not None else None
            self._write_task(task)
            if event is not None:
                self._write_event(event, task_hash)
            return task

    def merge_result(
        self,
        task_hash: str,
        claimer: str | None = None,
    ) -> CrowdTask | None:
        with self.locked():
            task = self.get_task(task_hash)
            if task is None or task.status != "done":
                return None
            trusted = self._load_json(self.trust_path).get("trusted", [])
            if trusted and claimer not in trusted:
                return None
            task.merged = True
            self._write_task(task)
            return task

    def accept_result(
        self,
        task_hash: str,
        event: NostrEvent | None = None,
    ) -> CrowdTask | None:
        with self.locked():
            task = self.get_task(task_hash)
            if task is None or task.status not in {"done", "claimed"}:
                return None
            task.status = "accepted"
            task.merged = True
            self._write_task(task)
            if event is not None:
                self._write_event(event, task_hash)
            return task

    def reject_result(
        self,
        task_hash: str,
        event: NostrEvent | None = None,
    ) -> CrowdTask | None:
        with self.locked():
            task = self.get_task(task_hash)
            if task is None or task.status not in {"done", "claimed"}:
                return None
            task.status = "rejected"
            self._write_task(task)
            if event is not None:
                self._write_event(event, task_hash)
            return task

    def expire_task(
        self,
        task_hash: str,
        event: NostrEvent | None = None,
    ) -> CrowdTask | None:
        with self.locked():
            task = self.get_task(task_hash)
            if task is None or task.status in {"done", "accepted", "rejected", "canceled", "expired"}:
                return None
            task.status = "expired"
            self._write_task(task)
            if event is not None:
                self._write_event(event, task_hash)
            return task

    def reopen_task(
        self,
        task_hash: str,
        event: NostrEvent | None = None,
    ) -> CrowdTask | None:
        with self.locked():
            task = self.get_task(task_hash)
            if task is None or task.status not in {"canceled", "rejected", "expired"}:
                return None
            task.status = "open"
            task.claimed_by = None
            task.claimed_at = None
            task.result_event_id = None
            self._write_task(task)
            if event is not None:
                self._write_event(event, task_hash)
            return task

    def write_artifact(
        self,
        task_hash: str,
        subdir: str,
        name: str,
        content: str,
    ) -> str:
        safe_sub = _safe_component(subdir)
        safe_name = _safe_component(name)
        dest = self._task_dir(task_hash) / safe_sub / safe_name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        return dest.relative_to(self.workspace).as_posix()

    def _load_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _save_json(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=True), encoding="utf-8")

    def _write_event(self, event: NostrEvent, task_hash: str) -> None:
        dest = self._event_dir(task_hash)
        dest.mkdir(parents=True, exist_ok=True)
        self._event_path(task_hash, event.id).write_text(
            json.dumps(event.to_dict(), indent=2, ensure_ascii=True),
            encoding="utf-8",
        )

    def append_event(self, event: NostrEvent, task_hash: str) -> None:
        with self.locked():
            self._write_event(event, task_hash)

    def list_events(self, task_hash: str) -> list[NostrEvent]:
        edir = self._event_dir(task_hash)
        if not edir.exists():
            return []
        events: list[NostrEvent] = []
        for p in edir.iterdir():
            if p.suffix != ".json" or not p.is_file():
                continue
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                events.append(NostrEvent.from_dict(data))
            except (json.JSONDecodeError, TypeError):
                continue
        events.sort(key=lambda e: (e.created_at, e.id))
        return events

    def iter_all_events(self) -> Iterator[tuple[str, NostrEvent]]:
        if not self.events_dir.exists():
            return
        for task_dir in self.events_dir.iterdir():
            if not task_dir.is_dir():
                continue
            for p in task_dir.iterdir():
                if p.suffix != ".json" or not p.is_file():
                    continue
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    yield task_dir.name, NostrEvent.from_dict(data)
                except (json.JSONDecodeError, TypeError):
                    continue

    def add_trusted(self, npub: str) -> None:
        trust = self._load_json(self.trust_path)
        trusted = set(trust.get("trusted", []))
        trusted.add(npub.strip())
        trust["trusted"] = sorted(trusted)
        self._save_json(self.trust_path, trust)

    def remove_trusted(self, npub: str) -> None:
        trust = self._load_json(self.trust_path)
        trusted = set(trust.get("trusted", []))
        trusted.discard(npub.strip())
        trust["trusted"] = sorted(trusted)
        self._save_json(self.trust_path, trust)

    def is_trusted(self, npub: str) -> bool:
        return npub.strip() in self._load_json(self.trust_path).get("trusted", [])

    def list_trusted(self) -> list[str]:
        return self._load_json(self.trust_path).get("trusted", [])

    def load_worker_profile(self) -> dict[str, Any]:
        return self._load_json(self.worker_profile_path)

    def save_worker_profile(self, profile: dict[str, Any]) -> None:
        self._save_json(self.worker_profile_path, profile)

    def add_embedding(self, task_hash: str, vector: list[float], tags: list[str] | None = None) -> None:
        index = self._load_json(self.vector_index_path)
        entries = index.get("entries", [])
        entries.append({
            "task_hash": task_hash,
            "vector": vector,
            "tags": sorted({t.lower() for t in (tags or [])}),
            "created_at": _utc_now(),
        })
        index["entries"] = entries
        self._save_json(self.vector_index_path, index)

    def search_embeddings(
        self,
        query_vector: list[float],
        top_k: int = 5,
        tags: list[str] | None = None,
    ) -> list[tuple[str, float]]:
        index = self._load_json(self.vector_index_path)
        entries = index.get("entries", [])
        matches: list[tuple[str, float]] = []
        tags_set = {t.lower() for t in (tags or [])}
        for entry in entries:
            if tags_set and not tags_set.intersection(set(entry.get("tags", []))):
                continue
            vec = entry.get("vector", [])
            if len(vec) != len(query_vector):
                continue
            sim = _cosine_similarity(query_vector, vec)
            matches.append((entry.get("task_hash", ""), sim))
        matches.sort(key=lambda x: x[1], reverse=True)
        return matches[:top_k]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class MemoryRelay:
    """In-memory Nostr-style relay used when no strfry binary is available.

    Stores events, indexes them by kind and ``d`` tag, and broadcasts to
    in-process subscribers. No signature validation is performed.
    """

    def __init__(self) -> None:
        self._events: list[NostrEvent] = []
        self._subs: dict[str, tuple[dict[str, Any], Callable[[NostrEvent], None]]] = {}
        self._lock = threading.Lock()

    def publish(self, event: NostrEvent) -> None:
        with self._lock:
            # Parameterised replaceable: keep only the newest event for each
            # (kind, pubkey, d) address (NIP-33).
            if event.kind >= 30000 and event.kind < 40000:
                d = _get_d_tag(event.tags)
                if d:
                    addr = (event.kind, event.pubkey, d)
                    same = [
                        e
                        for e in self._events
                        if (e.kind, e.pubkey, _get_d_tag(e.tags)) == addr
                    ]
                    if same and max(e.created_at for e in same) > event.created_at:
                        # A newer event already exists for this address.
                        callbacks = []
                    else:
                        self._events = [
                            e
                            for e in self._events
                            if (e.kind, e.pubkey, _get_d_tag(e.tags)) != addr
                        ]
                        self._events.append(event)
                        callbacks = [
                            callback
                            for _sub_id, (filter_, callback) in self._subs.items()
                            if _match_filter(event, filter_)
                        ]
                else:
                    self._events.append(event)
                    callbacks = [
                        callback
                        for _sub_id, (filter_, callback) in self._subs.items()
                        if _match_filter(event, filter_)
                    ]
            else:
                self._events.append(event)
                callbacks = [
                    callback
                    for _sub_id, (filter_, callback) in self._subs.items()
                    if _match_filter(event, filter_)
                ]
        for callback in callbacks:
            callback(event)

    def subscribe(
        self,
        sub_id: str,
        filter_: dict[str, Any],
        callback: Callable[[NostrEvent], None],
    ) -> None:
        with self._lock:
            self._subs[sub_id] = (filter_, callback)

    def unsubscribe(self, sub_id: str) -> None:
        with self._lock:
            self._subs.pop(sub_id, None)

    def query(self, filter_: dict[str, Any]) -> list[NostrEvent]:
        with self._lock:
            return [e for e in self._events if _match_filter(e, filter_)]

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
            self._subs.clear()


def _get_d_tag(tags: list[list[str]]) -> str | None:
    for tag in tags:
        if len(tag) >= 2 and tag[0] == "d":
            return tag[1]
    return None


def _safe_parse_json(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass
    return {}


def _task_hash_from_content(event: NostrEvent) -> str | None:
    """Best-effort fallback to find the referenced task hash in old events."""
    try:
        payload = json.loads(event.content)
        if isinstance(payload, dict):
            return payload.get("task_hash") or payload.get("task", {}).get("task_hash")
    except (json.JSONDecodeError, AttributeError):
        pass
    # Look for a 64-character hex e tag that may be the task event id.
    for tag in event.tags:
        if len(tag) >= 2 and tag[0] == "e" and len(tag[1]) == 64:
            return tag[1]
    return None


def _task_from_event(event: NostrEvent) -> CrowdTask:
    """Reconstruct a CrowdTask from a kind 31001 event payload."""
    payload = json.loads(event.content) if event.content else {}
    if not isinstance(payload, dict):
        payload = {}
    task_hash = _get_d_tag(event.tags) or _task_hash_from_content(event) or event.id
    encrypted_brief = payload.get("encrypted_brief")
    return CrowdTask(
        task_hash=task_hash,
        objective=payload.get("objective", ""),
        acceptance_criteria=payload.get("acceptance_criteria", ""),
        context_hash=payload.get("context_hash", ""),
        required_tier=payload.get("required_tier"),
        deadline=payload.get("deadline"),
        stake=payload.get("stake", "low"),
        tags=[t[1] for t in event.tags if len(t) >= 2 and t[0] == "t"],
        event_id=event.id,
        event_pubkey=event.pubkey,
        status="open",
        private=bool(payload.get("private", False)),
        private_allowed=list(payload.get("allowed", [])) if isinstance(payload.get("allowed"), list) else [],
        encrypted_brief=json.dumps(encrypted_brief, ensure_ascii=True) if isinstance(encrypted_brief, dict) else (encrypted_brief if isinstance(encrypted_brief, str) else None),
    )


def _match_filter(event: NostrEvent, filter_: dict[str, Any]) -> bool:
    kinds = filter_.get("kinds")
    if kinds and event.kind not in kinds:
        return False
    authors = filter_.get("authors")
    if authors and event.pubkey not in authors:
        return False
    ids = filter_.get("ids")
    if ids and event.id not in ids:
        return False
    since = filter_.get("since")
    if since and event.created_at < since:
        return False
    until = filter_.get("until")
    if until and event.created_at > until:
        return False
    for key, value in filter_.items():
        if key.startswith("#") and len(key) == 2:
            tag_name = key[1]
            wanted = value if isinstance(value, list) else [value]
            present = [t[1] for t in event.tags if len(t) >= 2 and t[0] == tag_name]
            if not any(w in present for w in wanted):
                return False
    return True


class StrfryWrapper:
    """Detect and spawn the local strfry relay and router binaries.

    Also provides a bridge into the strfry LMDB database via ``strfry import``
    (push) and ``strfry scan`` (pull) so OpenPlanter events actually flow into
    the relay that the router replicates upstream.
    """

    def __init__(self, root: Path, port: int = 7777) -> None:
        self.root = Path(root)
        self.port = port
        self.relay_proc: subprocess.Popen | None = None
        self.router_proc: subprocess.Popen | None = None

    @staticmethod
    def find_binary() -> Path | None:
        for name in ("strfry", "strfry.exe"):
            path = shutil.which(name)
            if path:
                return Path(path)
        return None

    def _write_relay_config(self) -> Path:
        conf = self.root / "strfry.conf"
        conf.write_text(
            f'db = "{(self.root / "db").as_posix()}/"\n'
            f"relay {{\n"
            f'    bind = "127.0.0.1"\n'
            f"    port = {self.port}\n"
            f"    info {{\n"
            f'        name = "OpenPlanter local strfry"\n'
            f'        description = "Local crowd task relay"\n'
            f"    }}\n"
            f"}}\n",
            encoding="utf-8",
        )
        (self.root / "db").mkdir(parents=True, exist_ok=True)
        return conf

    def _write_router_config(self, upstreams: list[str]) -> Path:
        conf = self.root / "router.conf"
        urls = ", ".join(f'"{u}"' for u in upstreams)
        kinds = list(map(str, [CROWD_KIND_TASK, CROWD_KIND_CLAIM, CROWD_KIND_RESULT, CROWD_KIND_AVAILABLE, CROWD_KIND_EMBEDDING, CROWD_KIND_CANCEL]))
        lines = [
            "streams {",
            f'    from_public {{\n        dir = "down"\n        urls = [{urls}]\n        filter = {{ kinds = [0, 10002, {", ".join(kinds)}] }}\n    }}',
            f'    to_public {{\n        dir = "up"\n        urls = [{urls}]\n        filter = {{ kinds = [{", ".join(kinds)}] }}\n    }}',
            "}",
        ]
        conf.write_text("\n".join(lines), encoding="utf-8")
        return conf

    def start_relay(self) -> str | None:
        binary = self.find_binary()
        if not binary:
            return None
        conf = self._write_relay_config()
        self.relay_proc = subprocess.Popen(
            [str(binary), "--config", str(conf), "relay"],
            cwd=str(self.root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return f"ws://127.0.0.1:{self.port}"

    def start_router(self, upstreams: list[str]) -> str | None:
        binary = self.find_binary()
        if not binary or not upstreams:
            return None
        conf = self._write_router_config(upstreams)
        # strfry router usage: ``strfry router <routerConfigFile>``
        self.router_proc = subprocess.Popen(
            [str(binary), "router", str(conf.name)],
            cwd=str(self.root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return str(conf)

    def is_running(self) -> bool:
        return self.relay_proc is not None and self.relay_proc.poll() is None

    def import_event(self, event: NostrEvent) -> bool:
        """Insert a single event into the strfry database via ``strfry import``."""
        binary = self.find_binary()
        if not binary or not self.is_running():
            return False
        try:
            line = json.dumps(event.to_dict(), separators=(",", ":"), ensure_ascii=True) + "\n"
            subprocess.run(
                [str(binary), "import", "--no-verify"],
                cwd=str(self.root),
                input=line,
                text=True,
                capture_output=True,
                timeout=10,
                check=True,
            )
            return True
        except Exception:
            return False

    def scan_events(self, filter_: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Scan the local strfry DB with a Nostr filter and return raw event dicts."""
        binary = self.find_binary()
        if not binary or not self.is_running():
            return []
        try:
            filter_json = json.dumps(filter_ or {}, separators=(",", ":"))
            result = subprocess.run(
                [str(binary), "scan", filter_json],
                cwd=str(self.root),
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
        except Exception:
            return []
        events: list[dict[str, Any]] = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return events

    def stop(self) -> None:
        for proc in (self.relay_proc, self.router_proc):
            if proc and proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                    proc.wait(timeout=2)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass


class CrowdClient:
    """High-level client that wires identity, local store, and relay together."""

    def __init__(
        self,
        store: CrowdStore,
        identity: CrowdIdentity | None = None,
        relay_uri: str | None = None,
        upstream_relays: list[str] | None = None,
        auto_spawn_strfry: bool = False,
        epsilon: float = 1.0,
        private_identity: CrowdIdentity | None = None,
        private_relays: list[str] | None = None,
    ) -> None:
        self.store = store
        self.identity = identity or CrowdIdentity()
        self.private_identity = private_identity or CrowdIdentity(self.identity.nsec_hex)
        self.relay_uri = relay_uri
        self.upstream_relays = list(upstream_relays or [])
        self.private_relays = list(private_relays or [])
        self.auto_spawn_strfry = auto_spawn_strfry
        self.epsilon = epsilon
        self.memory_relay = MemoryRelay()
        self._strfry: StrfryWrapper | None = None
        self._ingest_thread: threading.Thread | None = None
        self._stop_ingest = threading.Event()
        self._last_sync = 0
        self._local_server: Any = None
        self._local_server_thread: threading.Thread | None = None
        self.relay_pool = RelayPool(on_event=self._on_remote_event) if RelayPool else None
        if self.relay_uri:
            self.relay_pool.add(self.relay_uri) if self.relay_pool else None
        for uri in self.upstream_relays:
            self.relay_pool.add(uri) if self.relay_pool else None
        for uri in self.private_relays:
            self.relay_pool.add(uri) if self.relay_pool else None
        self._hydrate_memory_relay()

    def _hydrate_memory_relay(self) -> None:
        events = list(self.store.iter_all_events())
        events.sort(key=lambda item: item[1].created_at)
        for _task_hash, event in events:
            if not verify_event(event):
                warnings.warn(
                    f"Ignoring stored event with invalid id/signature: {event.id[:16]}...",
                    stacklevel=2,
                )
                continue
            self.memory_relay.publish(event)

    def _task_event_ref(self, task_hash: str) -> tuple[str, str]:
        """Return (event_id, publisher_pubkey) for a task if known, else (task_hash, '')."""
        task = self.store.get_task(task_hash)
        if task and task.event_id and task.event_pubkey:
            return task.event_id, task.event_pubkey
        return task_hash, ""

    def _bridge_to_strfry(self, event: NostrEvent) -> bool:
        """Push a local event into the strfry LMDB database (and upstream router)."""
        if self._strfry is None:
            return False
        return self._strfry.import_event(event)

    def _relay_publish(self, event: NostrEvent) -> None:
        """Send a signed event to every connected WebSocket relay (local + upstream)."""
        if self.relay_pool is not None:
            try:
                self.relay_pool.publish(event.to_dict())
            except Exception:
                pass
        self._bridge_to_strfry(event)

    def _relay_publish_private(self, event: NostrEvent) -> None:
        """Publish a private task event only to configured private relays."""
        if self.relay_pool is not None and self.private_relays:
            try:
                self.relay_pool.publish_to(event.to_dict(), self.private_relays)
            except Exception:
                pass
        # Private events stay off the public strfry bridge: do not call _bridge_to_strfry.

    def _ingest_from_strfry(self) -> None:
        """Pull events from the local strfry DB into the store and memory relay."""
        if self._strfry is None or not self._strfry.is_running():
            return
        since = max(0, self._last_sync - 1)
        filter_ = {
            "kinds": [CROWD_KIND_TASK, CROWD_KIND_CLAIM, CROWD_KIND_RESULT, CROWD_KIND_AVAILABLE, CROWD_KIND_EMBEDDING, CROWD_KIND_CANCEL, CROWD_KIND_FEEDBACK],
            "since": since,
        }
        max_seen = self._last_sync
        for raw in self._strfry.scan_events(filter_):
            try:
                event = NostrEvent.from_dict(raw)
                if not verify_event(event):
                    continue
                task_hash = _get_d_tag(event.tags) or _task_hash_from_content(event)
                if not task_hash:
                    continue
                self._ingest_event(event, task_hash)
                if event.created_at > max_seen:
                    max_seen = event.created_at
            except Exception:
                continue
        # Advance only after scanning so events created during the scan are
        # re-checked on the next poll (the -1 second overlap keeps the window
        # inclusive even with 1-second created_at granularity).
        self._last_sync = max(max_seen, _unix_now())

    def _ingest_event(self, event: NostrEvent, task_hash: str) -> None:
        """Persist a remote event and update local task state accordingly."""
        if self.store.get_task(task_hash) is None and event.kind == CROWD_KIND_TASK:
            self.store.create_task(_task_from_event(event), event=event)
            if _task_from_event(event).private:
                self.decrypt_private_task(task_hash)
            self.memory_relay.publish(event)
            return

        if event.kind == CROWD_KIND_CLAIM:
            claimer = event.pubkey
            if not claimer:
                payload = _safe_parse_json(event.content)
                claimer = payload.get("claimer", "")
            if self.store.claim_task(task_hash, claimer, event=event) is None:
                self.store.append_event(event, task_hash)
            else:
                self.memory_relay.publish(event)
            return

        if event.kind == CROWD_KIND_RESULT:
            task = self.store.get_task(task_hash)
            if task and task.status == "claimed" and task.claimed_by == event.pubkey:
                self.store.write_result(task_hash, event.content, event=event)
            else:
                self.store.append_event(event, task_hash)
            self.memory_relay.publish(event)
            return

        if event.kind == CROWD_KIND_CANCEL:
            self.store.cancel_task(task_hash, event=event)
            self.memory_relay.publish(event)
            return

        if event.kind == CROWD_KIND_FEEDBACK:
            task = self.store.get_task(task_hash)
            if task and (not task.event_pubkey or task.event_pubkey == event.pubkey):
                payload = _safe_parse_json(event.content)
                status = payload.get("status", "")
                if status == "accepted":
                    self.store.accept_result(task_hash, event=event)
                elif status == "rejected":
                    self.store.reject_result(task_hash, event=event)
                elif status == "expired":
                    self.store.expire_task(task_hash, event=event)
                elif status == "reopened":
                    self.store.reopen_task(task_hash, event=event)
                else:
                    self.store.append_event(event, task_hash)
            else:
                self.store.append_event(event, task_hash)
            self.memory_relay.publish(event)
            return

        if event.kind in {CROWD_KIND_AVAILABLE, CROWD_KIND_EMBEDDING}:
            self.store.append_event(event, task_hash)
            self.memory_relay.publish(event)
            return

        self.store.append_event(event, task_hash)
        self.memory_relay.publish(event)

    def _on_remote_event(self, raw: dict[str, Any]) -> None:
        """Callback used by RelayPool when a remote event arrives."""
        try:
            event = NostrEvent.from_dict(raw)
        except Exception:
            return
        if not verify_event(event):
            warnings.warn("Discarding event with invalid id/signature", stacklevel=2)
            return
        task_hash = _get_d_tag(event.tags) or _task_hash_from_content(event)
        if not task_hash:
            return
        self._ingest_event(event, task_hash)

    def _sync_loop(self) -> None:
        """Poll strfry DB periodically for new downstream events."""
        while not self._stop_ingest.wait(5.0):
            try:
                self._ingest_from_strfry()
            except Exception:
                pass

    def _start_federation_sync(self) -> None:
        """Start a background thread that periodically pulls from strfry."""
        if self._ingest_thread is not None:
            return
        self._stop_ingest.clear()
        self._ingest_thread = threading.Thread(target=self._sync_loop, daemon=True)
        self._ingest_thread.start()

    def start_local_relay(self, port: int = 7777, start_python_server: bool = True) -> str | None:
        if self.auto_spawn_strfry:
            self._strfry = StrfryWrapper(self.store.root / "strfry", port=port)
            uri = self._strfry.start_relay()
            if uri:
                self.relay_uri = uri
                if self.upstream_relays:
                    self._strfry.start_router(self.upstream_relays)
                if self.relay_pool is not None:
                    self.relay_pool.add(uri)
                time.sleep(0.5)
                self._ingest_from_strfry()
                self._start_federation_sync()
                return self.relay_uri
            warnings.warn(
                "strfry binary not found; falling back to in-memory relay",
                stacklevel=2,
            )

        self.relay_uri = f"ws://127.0.0.1:{port}"
        if start_python_server and CrowdRelayServer is not None:
            self._local_server = CrowdRelayServer(host="127.0.0.1", port=port)
            self._local_server_thread = self._local_server.start_in_thread()

        if self.relay_pool is not None:
            self.relay_pool.add(self.relay_uri)
            for uri in self.upstream_relays:
                self.relay_pool.add(uri)

        if self.upstream_relays and not self.auto_spawn_strfry:
            warnings.warn(
                "Upstream relays configured but --crowd-strfry not set; "
                "federation will not start unless a real relay is available",
                stacklevel=2,
            )
        return self.relay_uri

    def stop(self) -> None:
        self._stop_ingest.set()
        if self._ingest_thread is not None:
            self._ingest_thread.join(timeout=1)
            self._ingest_thread = None
        if self._strfry:
            self._strfry.stop()
        if self.relay_pool is not None:
            try:
                self.relay_pool.flush(timeout=3.0)
                self.relay_pool.stop()
            except Exception:
                pass
        if self._local_server is not None:
            try:
                self._local_server.stop()
                if self._local_server_thread is not None:
                    self._local_server_thread.join(timeout=2)
            except Exception:
                pass
            self._local_server = None
            self._local_server_thread = None

    def publish_task(self, task: CrowdTask, scope: str = "public") -> NostrEvent:
        content: dict[str, Any] = {
            "objective": task.objective,
            "acceptance_criteria": task.acceptance_criteria,
            "context_hash": task.context_hash,
            "required_tier": task.required_tier,
            "deadline": task.deadline,
            "stake": task.stake,
        }
        if task.private:
            content["private"] = True
            if task.private_allowed:
                content["allowed"] = list(task.private_allowed)
            if task.encrypted_brief:
                content["encrypted_brief"] = task.encrypted_brief
        event = NostrEvent(
            pubkey=self.identity.public_hex,
            created_at=_unix_now(),
            kind=CROWD_KIND_TASK,
            tags=_task_tags(task),
            content=json.dumps(content, ensure_ascii=True),
        )
        self.identity.sign_event(event)
        # Record the Nostr addressable coordinates for follow-up claims/results.
        task.event_id = event.id
        task.event_pubkey = event.pubkey
        self.memory_relay.publish(event)
        self.store.create_task(task, event=event)
        if task.private or scope == "private":
            if self.private_relays:
                self._relay_publish_private(event)
            else:
                warnings.warn(
                    "Private task has no private relays configured; the event is stored locally only.",
                    stacklevel=2,
                )
        else:
            self._relay_publish(event)
        return event

    def publish_private_task(
        self,
        task: CrowdTask,
        context: dict[str, Any] | None = None,
        allowed: list[str] | None = None,
    ) -> NostrEvent:
        """Publish a private task: brief is encrypted for the allowed recipients.

        The public event carries placeholder objective/acceptance criteria, an
        obfuscated context hash, and an encrypted brief that only the listed
        NIP-01 x-only recipients can read. The publisher is always added to the
        allowed list.
        """
        allowed = list(allowed or task.private_allowed or [])
        publisher_private_key = self.private_identity.public_hex
        if publisher_private_key not in allowed:
            allowed.insert(0, publisher_private_key)
        task.private_allowed = allowed

        sanitized_context = _sanitize_context(context or {})
        context_text = json.dumps(sanitized_context, sort_keys=True, ensure_ascii=True)
        task.context_hash = hashlib.sha256(context_text.encode("utf-8")).hexdigest()

        original_brief = json.dumps(
            {
                "objective": task.objective,
                "acceptance_criteria": task.acceptance_criteria,
                "context_hash": context_text,
            },
            ensure_ascii=True,
        )
        encrypted = _encrypt_brief(original_brief, self.private_identity.private_hex, allowed)
        task.encrypted_brief = json.dumps(encrypted, ensure_ascii=True)

        # Public placeholders keep the real brief off plain relays.
        task.objective = "Private task"
        task.acceptance_criteria = "See encrypted brief"
        task.private = True

        event = self.publish_task(task, scope="private")
        # The publisher can decrypt it locally for their own view.
        self.decrypt_private_task(task.task_hash, identity=self.private_identity)
        return event

    def decrypt_private_task(
        self,
        task_hash: str,
        identity: CrowdIdentity | None = None,
    ) -> CrowdTask | None:
        """Try to decrypt a private task brief using the provided identity.

        If successful, the plaintext is written back to the local task store so
        downstream commands can display the real objective and acceptance criteria.
        """
        task = self.store.get_task(task_hash)
        if task is None or not task.private or not task.encrypted_brief:
            return None
        identity = identity or self.private_identity
        try:
            encrypted = json.loads(task.encrypted_brief)
        except json.JSONDecodeError:
            return None
        plain = _decrypt_brief(encrypted, identity.private_hex)
        if plain is None:
            return None
        try:
            brief = json.loads(plain)
        except json.JSONDecodeError:
            return None
        if not isinstance(brief, dict):
            return None
        return self.store.update_task(
            task_hash,
            objective=brief.get("objective", task.objective),
            acceptance_criteria=brief.get("acceptance_criteria", task.acceptance_criteria),
            context_hash=hashlib.sha256(
                json.dumps(brief.get("context_hash", task.context_hash), sort_keys=True, ensure_ascii=True).encode("utf-8")
            ).hexdigest()
            if isinstance(brief.get("context_hash"), str)
            else task.context_hash,
        )

    def claim_task(self, task_hash: str) -> NostrEvent | None:
        claimer = self.identity.public_hex
        task_event_id, task_event_pubkey = self._task_event_ref(task_hash)
        tags: list[list[str]] = [["d", task_hash]]
        # Reference the task via a NIP-10-style ``e`` tag with the task event id.
        if len(str(task_event_id)) == 64:
            tags.append(["e", task_event_id, "", task_event_pubkey])
        tags.append(["p", claimer])
        event = NostrEvent(
            pubkey=claimer,
            created_at=_unix_now(),
            kind=CROWD_KIND_CLAIM,
            tags=tags,
            content=json.dumps({"task_hash": task_hash, "claimer": claimer}, ensure_ascii=True),
        )
        self.identity.sign_event(event)
        task = self.store.claim_task(task_hash, claimer, event=event)
        if task is None:
            return None
        self.memory_relay.publish(event)
        self._relay_publish(event)
        return event

    def cancel_task(self, task_hash: str) -> NostrEvent | None:
        task_event_id, task_event_pubkey = self._task_event_ref(task_hash)
        tags: list[list[str]] = [["d", task_hash]]
        if len(str(task_event_id)) == 64:
            tags.append(["e", task_event_id, "", task_event_pubkey])
        tags.append(["status", "canceled"])
        event = NostrEvent(
            pubkey=self.identity.public_hex,
            created_at=_unix_now(),
            kind=CROWD_KIND_CANCEL,
            tags=tags,
            content=json.dumps({"task_hash": task_hash, "status": "canceled"}, ensure_ascii=True),
        )
        self.identity.sign_event(event)
        task = self.store.cancel_task(task_hash, event=event)
        if task is None:
            return None
        self.memory_relay.publish(event)
        self._relay_publish(event)
        return event

    def return_result(
        self,
        task_hash: str,
        content: str,
        parent_pubkey: str | None = None,
    ) -> NostrEvent | None:
        task = self.store.get_task(task_hash)
        if task is None or task.claimed_by != self.identity.public_hex:
            return None
        task_event_id, task_event_pubkey = self._task_event_ref(task_hash)
        tags: list[list[str]] = [["d", task_hash]]
        if len(str(task_event_id)) == 64:
            tags.append(["e", task_event_id, "", task_event_pubkey])
        if parent_pubkey:
            tags.append(["p", parent_pubkey])
        event = NostrEvent(
            pubkey=self.identity.public_hex,
            created_at=_unix_now(),
            kind=CROWD_KIND_RESULT,
            tags=tags,
            content=content[:8000],
        )
        self.identity.sign_event(event)
        updated = self.store.write_result(task_hash, content, event=event)
        if updated is None:
            return None
        self.memory_relay.publish(event)
        self._relay_publish(event)
        return event

    def accept_result(self, task_hash: str) -> NostrEvent | None:
        task = self.store.get_task(task_hash)
        if task is None or task.status not in {"done", "claimed"}:
            return None
        if task.event_pubkey and task.event_pubkey != self.identity.public_hex:
            return None
        if task.claimed_by and self.store.list_trusted() and not self.store.is_trusted(task.claimed_by):
            warnings.warn(
                f"Refusing to accept result from untrusted worker {task.claimed_by[:16]}...",
                stacklevel=2,
            )
            return None
        task_event_id, task_event_pubkey = self._task_event_ref(task_hash)
        tags: list[list[str]] = [["d", task_hash], ["status", "accepted"]]
        if len(str(task_event_id)) == 64:
            tags.append(["e", task_event_id, "", task_event_pubkey])
        event = NostrEvent(
            pubkey=self.identity.public_hex,
            created_at=_unix_now(),
            kind=CROWD_KIND_FEEDBACK,
            tags=tags,
            content=json.dumps({"task_hash": task_hash, "status": "accepted"}, ensure_ascii=True),
        )
        self.identity.sign_event(event)
        if self.store.accept_result(task_hash, event=event) is None:
            return None
        self.memory_relay.publish(event)
        self._relay_publish(event)
        return event

    def reject_result(self, task_hash: str) -> NostrEvent | None:
        task = self.store.get_task(task_hash)
        if task is None or task.status not in {"done", "claimed"}:
            return None
        if task.event_pubkey and task.event_pubkey != self.identity.public_hex:
            return None
        task_event_id, task_event_pubkey = self._task_event_ref(task_hash)
        tags: list[list[str]] = [["d", task_hash], ["status", "rejected"]]
        if len(str(task_event_id)) == 64:
            tags.append(["e", task_event_id, "", task_event_pubkey])
        event = NostrEvent(
            pubkey=self.identity.public_hex,
            created_at=_unix_now(),
            kind=CROWD_KIND_FEEDBACK,
            tags=tags,
            content=json.dumps({"task_hash": task_hash, "status": "rejected"}, ensure_ascii=True),
        )
        self.identity.sign_event(event)
        if self.store.reject_result(task_hash, event=event) is None:
            return None
        self.memory_relay.publish(event)
        self._relay_publish(event)
        return event

    def expire_task(self, task_hash: str) -> NostrEvent | None:
        task = self.store.get_task(task_hash)
        if task is None or task.status in {"done", "accepted", "rejected", "canceled", "expired"}:
            return None
        if task.event_pubkey and task.event_pubkey != self.identity.public_hex:
            return None
        task_event_id, task_event_pubkey = self._task_event_ref(task_hash)
        tags: list[list[str]] = [["d", task_hash], ["status", "expired"]]
        if len(str(task_event_id)) == 64:
            tags.append(["e", task_event_id, "", task_event_pubkey])
        event = NostrEvent(
            pubkey=self.identity.public_hex,
            created_at=_unix_now(),
            kind=CROWD_KIND_FEEDBACK,
            tags=tags,
            content=json.dumps({"task_hash": task_hash, "status": "expired"}, ensure_ascii=True),
        )
        self.identity.sign_event(event)
        if self.store.expire_task(task_hash, event=event) is None:
            return None
        self.memory_relay.publish(event)
        self._relay_publish(event)
        return event

    def reopen_task(self, task_hash: str) -> NostrEvent | None:
        task = self.store.get_task(task_hash)
        if task is None or task.status not in {"canceled", "rejected", "expired"}:
            return None
        if task.event_pubkey and task.event_pubkey != self.identity.public_hex:
            return None
        task_event_id, task_event_pubkey = self._task_event_ref(task_hash)
        tags: list[list[str]] = [["d", task_hash], ["status", "reopened"]]
        if len(str(task_event_id)) == 64:
            tags.append(["e", task_event_id, "", task_event_pubkey])
        event = NostrEvent(
            pubkey=self.identity.public_hex,
            created_at=_unix_now(),
            kind=CROWD_KIND_FEEDBACK,
            tags=tags,
            content=json.dumps({"task_hash": task_hash, "status": "reopened"}, ensure_ascii=True),
        )
        self.identity.sign_event(event)
        if self.store.reopen_task(task_hash, event=event) is None:
            return None
        self.memory_relay.publish(event)
        self._relay_publish(event)
        return event

    def advertise_worker(self, tags: list[str], max_complexity: str = "medium", available: bool = True) -> NostrEvent:
        # One availability profile per public key; use the pubkey as d-tag to
        # avoid replacement collisions between different workers.
        d = self.identity.public_hex[:32] or "profile"
        event = NostrEvent(
            pubkey=self.identity.public_hex,
            created_at=_unix_now(),
            kind=CROWD_KIND_AVAILABLE,
            tags=[["d", d]] + [["t", t] for t in tags],
            content=json.dumps({
                "max_complexity": max_complexity,
                "available": available,
                "tags": sorted({t.lower() for t in tags}),
            }, ensure_ascii=True),
        )
        self.identity.sign_event(event)
        self.memory_relay.publish(event)
        self._relay_publish(event)
        return event

    def publish_embedding(
        self,
        task_hash: str,
        vector: list[float],
        tags: list[str] | None = None,
    ) -> NostrEvent:
        noisy = NoisyEmbedding(epsilon=self.epsilon).perturb(vector)
        task_event_id, task_event_pubkey = self._task_event_ref(task_hash)
        etags: list[list[str]] = [["d", task_hash]]
        if len(str(task_event_id)) == 64:
            etags.append(["e", task_event_id, "", task_event_pubkey])
        etags += [["t", t] for t in (tags or [])]
        event = NostrEvent(
            pubkey=self.identity.public_hex,
            created_at=_unix_now(),
            kind=CROWD_KIND_EMBEDDING,
            tags=etags,
            content=json.dumps({"task_hash": task_hash, "vector": noisy}, ensure_ascii=True),
        )
        self.identity.sign_event(event)
        self.memory_relay.publish(event)
        self.store.add_embedding(task_hash, noisy, tags)
        self.store.append_event(event, task_hash)
        self._relay_publish(event)
        return event


def _task_tags(task: CrowdTask) -> list[list[str]]:
    tags: list[list[str]] = [["d", task.task_hash]]
    if task.parent_task_hash:
        tags.append(["e", task.parent_task_hash, ""])
    if task.tags:
        for t in task.tags:
            tags.append(["t", t])
    tags.append(["stake", task.stake])
    return tags


class NoisyEmbedding:
    """Randomized noise for embedding vectors.

    This is intentionally *not* a formal differential-privacy mechanism. A real
    DP guarantee would require sensitivity, clipping, delta accounting, and an
    explicit privacy budget. OpenPlanter instead applies simple Laplace/Gaussian
    noise controlled by ``epsilon`` to make exact vector matching harder.
    """

    MIN_EPSILON = 1e-9

    def __init__(self, epsilon: float = 1.0, mechanism: str = "gaussian") -> None:
        self.epsilon = max(float(epsilon), self.MIN_EPSILON)
        self.mechanism = mechanism

    def perturb(self, vector: list[float]) -> list[float]:
        if not vector:
            return vector
        scale = 1.0 / self.epsilon
        if self.mechanism == "laplace":
            return [v + self._laplace(scale) for v in vector]
        return [v + random.gauss(0.0, scale) for v in vector]

    @staticmethod
    def _laplace(scale: float) -> float:
        u = random.random() - 0.5
        return -scale * math.copysign(math.log(1.0 - 2.0 * abs(u)), u)

    def __enter__(self) -> "NoisyEmbedding":
        return self

    def __exit__(self, *args: Any) -> None:
        pass


def crowd_client_from_config(
    config: AgentConfig,
    settings: dict[str, Any] | None = None,
) -> CrowdClient:
    """Build a CrowdClient from runtime config + persisted settings."""
    store = CrowdStore(config.workspace, config.session_root_dir)
    nsec = settings.get("crowd_nsec") if settings else None
    identity = CrowdIdentity(nsec) if nsec else CrowdIdentity()
    upstreams = settings.get("crowd_relays", []) if settings else []
    private_nsec = settings.get("crowd_private_nsec") if settings else None
    private_identity = CrowdIdentity(private_nsec) if private_nsec else None
    private_relays = settings.get("crowd_private_relays", []) if settings else []
    auto_spawn = getattr(config, "crowd_auto_spawn_strfry", False)
    epsilon = (
        float(settings.get("crowd_epsilon"))
        if settings and settings.get("crowd_epsilon") is not None
        else 1.0
    )
    return CrowdClient(
        store=store,
        identity=identity,
        upstream_relays=upstreams,
        auto_spawn_strfry=auto_spawn,
        epsilon=epsilon,
        private_identity=private_identity,
        private_relays=private_relays,
    )


def _load_settings(workspace: Path, session_root_dir: str) -> dict[str, Any]:
    path = (workspace / session_root_dir / "settings.json").resolve()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
