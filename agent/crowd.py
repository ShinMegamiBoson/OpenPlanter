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

CROWD_KIND_TASK = 31001
CROWD_KIND_CLAIM = 31002
CROWD_KIND_RESULT = 31003
CROWD_KIND_AVAILABLE = 31004
CROWD_KIND_EMBEDDING = 31005
CROWD_KIND_CANCEL = 31006

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
    status: str = "open"
    created_at: str = field(default_factory=_utc_now)
    claimed_by: str | None = None
    claimed_at: str | None = None
    result_event_id: str | None = None
    merged: bool = False
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
            status="open",
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
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self.events_dir.mkdir(parents=True, exist_ok=True)

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

    def merge_result(self, task_hash: str) -> CrowdTask | None:
        with self.locked():
            task = self.get_task(task_hash)
            if task is None or task.status != "done":
                return None
            task.merged = True
            self._write_task(task)
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
            # Parameterised replaceable: replace previous event for same (kind, pubkey, d).
            if event.kind >= 30000 and event.kind < 40000:
                d = _get_d_tag(event.tags)
                if d:
                    self._events = [
                        e
                        for e in self._events
                        if not (e.kind == event.kind and e.pubkey == event.pubkey and _get_d_tag(e.tags) == d)
                    ]
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
    ) -> None:
        self.store = store
        self.identity = identity or CrowdIdentity()
        self.relay_uri = relay_uri
        self.upstream_relays = list(upstream_relays or [])
        self.auto_spawn_strfry = auto_spawn_strfry
        self.epsilon = epsilon
        self.memory_relay = MemoryRelay()
        self._strfry: StrfryWrapper | None = None
        self._ingest_thread: threading.Thread | None = None
        self._stop_ingest = threading.Event()
        self._last_sync = 0
        self._hydrate_memory_relay()

    def _hydrate_memory_relay(self) -> None:
        events = list(self.store.iter_all_events())
        events.sort(key=lambda item: item[1].created_at)
        for _task_hash, event in events:
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

    def _ingest_from_strfry(self) -> None:
        """Pull events from the local strfry DB into the store and memory relay."""
        if self._strfry is None or not self._strfry.is_running():
            return
        since = max(0, self._last_sync - 1)
        filter_ = {
            "kinds": [CROWD_KIND_TASK, CROWD_KIND_CLAIM, CROWD_KIND_RESULT, CROWD_KIND_AVAILABLE, CROWD_KIND_EMBEDDING, CROWD_KIND_CANCEL],
            "since": since,
        }
        self._last_sync = _unix_now()
        for raw in self._strfry.scan_events(filter_):
            try:
                event = NostrEvent.from_dict(raw)
                if not verify_event(event):
                    continue
                task_hash = _get_d_tag(event.tags) or _task_hash_from_content(event)
                if not task_hash:
                    continue
                if self.store.get_task(task_hash) is None and event.kind == CROWD_KIND_TASK:
                    self.store.create_task(_task_from_event(event), event=event)
                self.store.append_event(event, task_hash)
                self.memory_relay.publish(event)
            except Exception:
                continue

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

    def start_local_relay(self, port: int = 7777) -> str | None:
        if self.auto_spawn_strfry:
            self._strfry = StrfryWrapper(self.store.root / "strfry", port=port)
            uri = self._strfry.start_relay()
            if uri:
                self.relay_uri = uri
                if self.upstream_relays:
                    self._strfry.start_router(self.upstream_relays)
                # Wait briefly for strfry to open its DB, then hydrate.
                time.sleep(0.5)
                self._ingest_from_strfry()
                self._start_federation_sync()
                return self.relay_uri
            warnings.warn(
                "strfry binary not found; falling back to in-memory relay",
                stacklevel=2,
            )
        self.relay_uri = f"ws://127.0.0.1:{port}"
        if self.upstream_relays and not self.auto_spawn_strfry:
            warnings.warn(
                "Upstream relays configured but --crowd-strfry not set; "
                "federation will not start for the in-memory relay",
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

    def publish_task(self, task: CrowdTask) -> NostrEvent:
        event = NostrEvent(
            pubkey=self.identity.public_hex,
            created_at=_unix_now(),
            kind=CROWD_KIND_TASK,
            tags=_task_tags(task),
            content=json.dumps({
                "objective": task.objective,
                "acceptance_criteria": task.acceptance_criteria,
                "context_hash": task.context_hash,
                "required_tier": task.required_tier,
                "deadline": task.deadline,
                "stake": task.stake,
            }, ensure_ascii=True),
        )
        self.identity.sign_event(event)
        # Record the Nostr addressable coordinates for follow-up claims/results.
        task.event_id = event.id
        task.event_pubkey = event.pubkey
        self.memory_relay.publish(event)
        self.store.create_task(task, event=event)
        self._bridge_to_strfry(event)
        return event

    def claim_task(self, task_hash: str, pubkey: str | None = None) -> NostrEvent | None:
        claimer = self.identity.public_hex
        if pubkey is not None and pubkey != claimer:
            warnings.warn(
                "claim_task() pubkey argument is only advisory and must match the signer; "
                "the event will be signed with the local identity",
                stacklevel=2,
            )
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
        self._bridge_to_strfry(event)
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
        self._bridge_to_strfry(event)
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
        self._bridge_to_strfry(event)
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
        self._bridge_to_strfry(event)
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
        self._bridge_to_strfry(event)
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
    )


def _load_settings(workspace: Path, session_root_dir: str) -> dict[str, Any]:
    path = (workspace / session_root_dir / "settings.json").resolve()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
