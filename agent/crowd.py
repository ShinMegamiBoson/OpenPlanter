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
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .config import AgentConfig

CROWD_KIND_TASK = 31001
CROWD_KIND_CLAIM = 31002
CROWD_KIND_RESULT = 31003
CROWD_KIND_AVAILABLE = 31004
CROWD_KIND_EMBEDDING = 31005

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
    return hashlib.sha256(json.dumps(normed, ensure_ascii=False).encode("utf-8")).hexdigest()


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
        except Exception:
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
        self.trust_path = self.root / "trust.json"
        self.worker_profile_path = self.root / "worker_profile.json"
        self.vector_index_path = self.root / "vector_index.json"
        self._lock = threading.Lock()
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        self.tasks_dir.mkdir(parents=True, exist_ok=True)

    def _task_dir(self, task_hash: str) -> Path:
        return self.tasks_dir / task_hash

    def _metadata_path(self, task_hash: str) -> Path:
        return self._task_dir(task_hash) / "metadata.json"

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
        objective: str,
        acceptance_criteria: str,
        context_hash: str = "",
        parent_session_id: str | None = None,
        parent_task_hash: str | None = None,
        tags: list[str] | None = None,
        stake: str = "low",
        required_tier: str | None = None,
        deadline: str | None = None,
    ) -> CrowdTask:
        task = CrowdTask.build(
            objective=objective,
            acceptance_criteria=acceptance_criteria,
            context_hash=context_hash,
            parent_session_id=parent_session_id,
            parent_task_hash=parent_task_hash,
            tags=tags,
            stake=stake,
            required_tier=required_tier,
            deadline=deadline,
        )
        self._write_task(task)
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
        task = self.get_task(task_hash)
        if task is None:
            return None
        for key, value in updates.items():
            if hasattr(task, key):
                setattr(task, key, value)
        self._write_task(task)
        return task

    def claim_task(self, task_hash: str, worker_pubkey: str) -> CrowdTask | None:
        with self._lock:
            task = self.get_task(task_hash)
            if task is None or task.status != "open":
                return None
            task.status = "claimed"
            task.claimed_by = worker_pubkey
            task.claimed_at = _utc_now()
            self._write_task(task)
            return task

    def write_result(
        self,
        task_hash: str,
        content: str,
        result_event_id: str | None = None,
    ) -> CrowdTask | None:
        with self._lock:
            task = self.get_task(task_hash)
            if task is None or task.status != "claimed":
                return None
            rdir = self.result_dir(task_hash)
            (rdir / "result.md").write_text(content, encoding="utf-8")
            task.status = "done"
            task.result_event_id = result_event_id
            self._write_task(task)
            return task

    def merge_result(self, task_hash: str) -> CrowdTask | None:
        with self._lock:
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
            for _sub_id, (filter_, callback) in self._subs.items():
                if _match_filter(event, filter_):
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
    """Detect and spawn the local strfry relay and router binaries."""

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
        lines = [
            "streams {",
            f'    from_public {{\n        dir = "down"\n        urls = [{urls}]\n        filter = {{ kinds = [0, 10002, 31001, 31002, 31003, 31004, 31005] }}\n    }}',
            f'    to_public {{\n        dir = "up"\n        urls = [{urls}]\n        filter = {{ kinds = [31001, 31002, 31003, 31004, 31005] }}\n    }}',
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
        self.router_proc = subprocess.Popen(
            [str(binary), "--config", str(conf), "router"],
            cwd=str(self.root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return str(conf)

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
    ) -> None:
        self.store = store
        self.identity = identity or CrowdIdentity()
        self.relay_uri = relay_uri
        self.upstream_relays = upstream_relays or []
        self.memory_relay = MemoryRelay()
        self._strfry: StrfryWrapper | None = None

    def local_uri(self) -> str:
        return self.relay_uri or "ws://127.0.0.1:7777"

    def start_local_relay(self, port: int = 7777) -> str | None:
        self._strfry = StrfryWrapper(self.store.workspace / self.store.root.relative_to(self.store.workspace) / "strfry", port=port)
        uri = self._strfry.start_relay()
        if uri:
            self.relay_uri = uri
            return uri
        # Fall back to the in-memory relay on the same URI for local-only use,
        # but do not actually bind a websocket server in this scaffold.
        self.relay_uri = f"ws://127.0.0.1:{port}"
        return self.relay_uri

    def stop(self) -> None:
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
        self.memory_relay.publish(event)
        self.store.create_task(
            objective=task.objective,
            acceptance_criteria=task.acceptance_criteria,
            context_hash=task.context_hash,
            parent_session_id=task.parent_session_id,
            parent_task_hash=task.parent_task_hash,
            tags=task.tags,
            stake=task.stake,
            required_tier=task.required_tier,
            deadline=task.deadline,
        )
        return event

    def claim_task(self, task_hash: str, pubkey: str | None = None) -> NostrEvent | None:
        worker = pubkey or self.identity.public_hex
        task = self.store.claim_task(task_hash, worker)
        if task is None:
            return None
        event = NostrEvent(
            pubkey=worker,
            created_at=_unix_now(),
            kind=CROWD_KIND_CLAIM,
            tags=[["e", task_hash], ["p", task.claimed_by or worker]],
            content=json.dumps({"task_hash": task_hash, "claimer": worker}, ensure_ascii=True),
        )
        self.identity.sign_event(event)
        self.memory_relay.publish(event)
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
        self.store.write_result(task_hash, content)
        tags = [["e", task_hash]]
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
        self.memory_relay.publish(event)
        return event

    def advertise_worker(self, tags: list[str], max_complexity: str = "medium", available: bool = True) -> NostrEvent:
        event = NostrEvent(
            pubkey=self.identity.public_hex,
            created_at=_unix_now(),
            kind=CROWD_KIND_AVAILABLE,
            tags=[["t", t] for t in tags],
            content=json.dumps({
                "max_complexity": max_complexity,
                "available": available,
                "tags": sorted({t.lower() for t in tags}),
            }, ensure_ascii=True),
        )
        self.identity.sign_event(event)
        self.memory_relay.publish(event)
        return event

    def publish_embedding(
        self,
        task_hash: str,
        vector: list[float],
        tags: list[str] | None = None,
    ) -> NostrEvent:
        event = NostrEvent(
            pubkey=self.identity.public_hex,
            created_at=_unix_now(),
            kind=CROWD_KIND_EMBEDDING,
            tags=[["d", task_hash]] + [["t", t] for t in (tags or [])],
            content=json.dumps({"task_hash": task_hash, "vector": vector}, ensure_ascii=True),
        )
        self.identity.sign_event(event)
        self.memory_relay.publish(event)
        self.store.add_embedding(task_hash, vector, tags)
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


class DifferentialPrivacyEmbedding:
    """Local differential privacy noise for embedding vectors."""

    def __init__(self, epsilon: float = 1.0, mechanism: str = "gaussian") -> None:
        self.epsilon = max(epsilon, 0.0)
        self.mechanism = mechanism

    def perturb(self, vector: list[float]) -> list[float]:
        if self.epsilon == 0 or not vector:
            return vector
        scale = 1.0 / self.epsilon
        if self.mechanism == "laplace":
            return [v + self._laplace(scale) for v in vector]
        return [v + random.gauss(0.0, scale) for v in vector]

    @staticmethod
    def _laplace(scale: float) -> float:
        u = random.random() - 0.5
        return -scale * math.copysign(math.log(1.0 - 2.0 * abs(u)), u)

    def __enter__(self) -> "DifferentialPrivacyEmbedding":
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
    return CrowdClient(store=store, identity=identity, upstream_relays=upstreams)


def _load_settings(workspace: Path, session_root_dir: str) -> dict[str, Any]:
    path = (workspace / session_root_dir / "settings.json").resolve()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
