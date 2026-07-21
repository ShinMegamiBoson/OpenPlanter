"""Tests for the OpenPlanter Crowd marketplace.

These tests exercise the end-to-end lifecycle, private tasks, and edge cases
using an in-memory WebSocket relay. They do not require an external strfry
binary.
"""

from __future__ import annotations

import socket
import tempfile
import time
from pathlib import Path

import pytest

from agent.crowd import (
    CROWD_KIND_TASK,
    CrowdClient,
    CrowdIdentity,
    CrowdStore,
    CrowdTask,
    NostrEvent,
    verify_event,
)
from agent.relay_server import CrowdRelayServer


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def tmp_workspace():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.fixture
def relay():
    port = _free_port()
    server = CrowdRelayServer(host="127.0.0.1", port=port)
    server.start_in_thread()
    try:
        yield f"ws://127.0.0.1:{port}"
    finally:
        server.stop()


def _wait_for(condition, timeout: float = 10.0, interval: float = 0.05):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        result = condition()
        if result:
            return result
        time.sleep(interval)
    raise TimeoutError("condition never became true")


def test_event_id_and_signature_verification():
    """A signed task event verifies, a tampered one does not."""
    identity = CrowdIdentity()
    task = CrowdTask.build(objective="test", acceptance_criteria="ok", tags=["t"])
    event = NostrEvent(
        pubkey=identity.public_hex,
        created_at=1234567890,
        kind=CROWD_KIND_TASK,
        tags=[["d", task.task_hash], ["t", "t"]],
        content='{"objective":"test"}',
    )
    identity.sign_event(event)
    assert verify_event(event) is True

    event.content = '{"objective":"tampered"}'
    assert verify_event(event) is False


def test_public_lifecycle_over_relay(tmp_workspace, relay):
    """Publish → discover → claim → submit result → accept over WebSocket."""
    publisher_id = CrowdIdentity()
    worker_id = CrowdIdentity()

    pub_dir = tmp_workspace / "pub"
    worker_dir = tmp_workspace / "worker"
    pub_dir.mkdir()
    worker_dir.mkdir()

    pub = CrowdClient(
        store=CrowdStore(pub_dir, ""),
        identity=publisher_id,
        relay_uri=relay,
    )
    worker = CrowdClient(
        store=CrowdStore(worker_dir, ""),
        identity=worker_id,
        relay_uri=relay,
    )

    # Wait for subscriptions to open.
    time.sleep(0.5)

    task = CrowdTask.build(
        objective="add 2 and 2",
        acceptance_criteria="return 4",
        tags=["math"],
    )
    pub.publish_task(task)

    remote = _wait_for(lambda: worker.store.get_task(task.task_hash))
    assert remote.objective == task.objective
    assert remote.status == "open"

    worker.claim_task(task.task_hash)

    def _claimed():
        t = pub.store.get_task(task.task_hash)
        return t if t and t.status == "claimed" else None

    remote = _wait_for(_claimed)
    assert remote.claimed_by == worker_id.public_hex

    worker.return_result(task.task_hash, "4")

    def _done():
        t = pub.store.get_task(task.task_hash)
        return t if t and t.status == "done" else None

    remote = _wait_for(_done)
    assert remote.status == "done"

    pub.accept_result(task.task_hash)
    assert pub.store.get_task(task.task_hash).status == "accepted"


def test_private_task_exchange(tmp_workspace, relay):
    """Encrypted briefs are only readable by allowed private identities."""
    publisher_private = CrowdIdentity()
    worker_private = CrowdIdentity()
    eavesdropper_private = CrowdIdentity()

    pub_dir = tmp_workspace / "pub"
    worker_dir = tmp_workspace / "worker"
    pub_dir.mkdir()
    worker_dir.mkdir()

    pub = CrowdClient(
        store=CrowdStore(pub_dir, ""),
        identity=CrowdIdentity(),
        private_identity=publisher_private,
        relay_uri=relay,
        private_relays=[relay],
    )
    worker = CrowdClient(
        store=CrowdStore(worker_dir, ""),
        identity=CrowdIdentity(),
        private_identity=worker_private,
        relay_uri=relay,
        private_relays=[relay],
    )
    time.sleep(0.5)

    task = CrowdTask.build(
        objective="Use secret API key",
        acceptance_criteria="Do not leak the key",
        tags=["private"],
        private=True,
        private_allowed=[worker_private.public_hex],
    )
    context = {"api_key": "supersecret", "data": list(range(1000))}
    pub.publish_private_task(task, context=context, allowed=[worker_private.public_hex])

    def _decrypted():
        t = worker.store.get_task(task.task_hash)
        if t and "secret API key" in t.objective:
            return t
        return None

    remote = _wait_for(_decrypted, timeout=5.0)
    assert remote.private is True
    # The sanitized public context hash must not contain the literal secret.
    assert "supersecret" not in remote.context_hash

    # An unrelated private identity cannot decrypt the brief.
    other = CrowdClient(
        store=CrowdStore(tmp_workspace / "other", ""),
        identity=CrowdIdentity(),
        private_identity=eavesdropper_private,
        relay_uri=relay,
        private_relays=[relay],
    )
    time.sleep(0.5)
    other_task = _wait_for(lambda: other.store.get_task(task.task_hash))
    decrypted = other.decrypt_private_task(other_task.task_hash)
    assert decrypted is None


def test_cancel_propagates_over_relay(tmp_workspace, relay):
    publisher_id = CrowdIdentity()
    worker_dir = tmp_workspace / "worker"
    worker_dir.mkdir()

    pub = CrowdClient(
        store=CrowdStore(tmp_workspace / "pub", ""),
        identity=publisher_id,
        relay_uri=relay,
    )
    worker = CrowdClient(
        store=CrowdStore(worker_dir, ""),
        relay_uri=relay,
    )
    time.sleep(0.5)

    task = CrowdTask.build(objective="cancel me", acceptance_criteria="n/a", tags=[])
    pub.publish_task(task)
    remote = _wait_for(lambda: worker.store.get_task(task.task_hash))
    pub.cancel_task(task.task_hash)

    def _canceled():
        t = worker.store.get_task(task.task_hash)
        return t if t and t.status == "canceled" else None

    remote = _wait_for(_canceled)
    assert remote.status == "canceled"


def test_simultaneous_claim_is_atomic(tmp_workspace):
    """Two workers racing on the same task must produce exactly one success."""
    publisher_id = CrowdIdentity()
    store = CrowdStore(tmp_workspace / "shared", "")
    pub = CrowdClient(store=store, identity=publisher_id)

    task = CrowdTask.build(objective="race", acceptance_criteria="first", tags=["race"])
    pub.publish_task(task)

    worker1 = CrowdClient(store=store, identity=CrowdIdentity())
    worker2 = CrowdClient(store=store, identity=CrowdIdentity())

    results = []
    for w in (worker1, worker2):
        ev = w.claim_task(task.task_hash)
        results.append(ev is not None)

    assert sum(results) == 1, results
    assert store.get_task(task.task_hash).status == "claimed"
