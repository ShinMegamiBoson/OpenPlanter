"""WebSocket Nostr relay adapter for OpenPlanter Crowd.

Provides an actual relay protocol implementation (``["EVENT", ...]``,
``["REQ", ...]``, ``["CLOSE", ...]``) over WebSockets so two OpenPlanter
processes can publish and subscribe to tasks and results.
"""

from __future__ import annotations

import asyncio
import json
import logging
import queue
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

try:
    import websockets
except Exception:  # pragma: no cover - optional runtime
    websockets = None  # type: ignore[assignment]

LOGGER = logging.getLogger(__name__)

# Default kinds the adapter cares about.
CROWD_KIND_TASK = 31001
CROWD_KIND_CLAIM = 31002
CROWD_KIND_RESULT = 31003
CROWD_KIND_AVAILABLE = 31004
CROWD_KIND_EMBEDDING = 31005
CROWD_KIND_CANCEL = 31006
CROWD_KIND_FEEDBACK = 31007

CROWD_KINDS = [
    CROWD_KIND_TASK,
    CROWD_KIND_CLAIM,
    CROWD_KIND_RESULT,
    CROWD_KIND_AVAILABLE,
    CROWD_KIND_EMBEDDING,
    CROWD_KIND_CANCEL,
    CROWD_KIND_FEEDBACK,
]


class RelayError(RuntimeError):
    pass


@dataclass
class _Outgoing:
    text: str


@dataclass
class _Subscription:
    filters: list[dict[str, Any]]


class NostrRelayConnection:
    """WebSocket connection to a single Nostr relay, with auto-reconnect."""

    def __init__(
        self,
        uri: str,
        name: str | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        on_status: Callable[[str, str], None] | None = None,
        connect_timeout: float = 5.0,
        reconnect_interval: float = 5.0,
    ) -> None:
        self.uri = uri
        self.name = name or uri
        self.on_event = on_event
        self.on_status = on_status
        self.connect_timeout = connect_timeout
        self.reconnect_interval = reconnect_interval

        self._ws: Any = None
        self._pending: queue.Queue[_Outgoing] = queue.Queue()
        self._subscriptions: dict[str, _Subscription] = {}
        self._stop = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._connected = threading.Event()
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            if self._loop is not None and self._loop.is_running():
                asyncio.run_coroutine_threadsafe(self._disconnect(), self._loop)
        except Exception:
            pass
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def is_connected(self) -> bool:
        return self._connected.is_set() and self._ws is not None

    def flush(self, timeout: float = 3.0) -> bool:
        """Wait for the outbound message queue to drain up to ``timeout``."""
        self._connected.wait(timeout)
        if not self.is_connected():
            return False
        deadline = time.monotonic() + timeout
        while not self._pending.empty() and time.monotonic() < deadline:
            time.sleep(0.05)
        return self._pending.empty()

    def publish(self, event: dict[str, Any]) -> None:
        self.send(["EVENT", event])

    def subscribe(
        self,
        filters: dict[str, Any] | list[dict[str, Any]] | None = None,
        sub_id: str | None = None,
    ) -> str:
        sub_id = sub_id or secrets.token_hex(4)
        filters = filters or [{"kinds": CROWD_KINDS}]
        if isinstance(filters, dict):
            filters = [filters]
        with self._lock:
            self._subscriptions[sub_id] = _Subscription(filters=filters)
        self.send(["REQ", sub_id, *filters])
        return sub_id

    def unsubscribe(self, sub_id: str) -> None:
        with self._lock:
            self._subscriptions.pop(sub_id, None)
        self.send(["CLOSE", sub_id])

    def send(self, msg: list[Any]) -> None:
        self._pending.put(_Outgoing(text=json.dumps(msg, separators=(",", ":"))))

    def _run(self) -> None:
        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self._main_loop())
        finally:
            try:
                self._loop.close()
            except Exception:
                pass
            self._loop = None

    async def _main_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self._connect_and_run()
            except Exception as exc:
                LOGGER.debug("relay %s connection failed: %s", self.name, exc)
            if self._stop.is_set():
                break
            self._connected.clear()
            self._notify_status("disconnected", str(self.uri))
            try:
                await asyncio.wait_for(
                    self._wait_for_stop(self.reconnect_interval),
                    timeout=self.reconnect_interval + 1,
                )
            except asyncio.TimeoutError:
                pass

    async def _wait_for_stop(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and not self._stop.is_set():
            await asyncio.sleep(0.1)

    async def _connect_and_run(self) -> None:
        if websockets is None:
            raise RelayError("websockets library is not installed")

        LOGGER.info("relay connecting to %s", self.uri)
        self._ws = await asyncio.wait_for(
            websockets.connect(self.uri), timeout=self.connect_timeout
        )
        self._connected.set()
        self._notify_status("connected", str(self.uri))
        await self._flush_subscriptions()
        while not self._stop.is_set():
            await self._pump_io()

    async def _pump_io(self) -> None:
        if self._ws is None:
            return

        # Outgoing queue -> websocket
        try:
            text = self._pending.get_nowait().text
            await self._ws.send(text)
        except queue.Empty:
            pass

        # Incoming messages
        try:
            raw = await asyncio.wait_for(self._ws.recv(), timeout=0.5)
        except asyncio.TimeoutError:
            return
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        await self._handle_message(raw)

    async def _disconnect(self) -> None:
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    async def _flush_subscriptions(self) -> None:
        with self._lock:
            subs = list(self._subscriptions.items())
        for sub_id, sub in subs:
            self.send(["REQ", sub_id, *sub.filters])
        # Flush any remaining outbound messages sent before connection.
        while True:
            try:
                text = self._pending.get_nowait().text
                await self._ws.send(text)
            except queue.Empty:
                break
            except Exception:
                break

    async def _handle_message(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return
        if not isinstance(msg, list) or len(msg) == 0:
            return
        cmd = msg[0]
        if cmd == "EVENT" and len(msg) >= 3:
            await self._dispatch_event(msg[2])
        elif cmd == "OK" and len(msg) >= 3:
            self._notify_status("ok", f"{msg[1]}: {msg[2]}")
        elif cmd == "EOSE":
            self._notify_status("eose", str(msg[1] if len(msg) > 1 else ""))
        elif cmd == "NOTICE":
            self._notify_status("notice", str(msg[1] if len(msg) > 1 else ""))

    async def _dispatch_event(self, event: dict[str, Any]) -> None:
        if not isinstance(event, dict):
            return
        if self.on_event:
            try:
                self.on_event(event)
            except Exception as exc:
                LOGGER.warning("relay %s on_event failed: %s", self.name, exc)

    def _notify_status(self, level: str, text: str) -> None:
        if self.on_status:
            try:
                self.on_status(self.name, f"{level}:{text}")
            except Exception:
                pass


class RelayPool:
    """Pool of WebSocket relay connections used by CrowdClient."""

    def __init__(
        self,
        uris: list[str] | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        on_status: Callable[[str, str], None] | None = None,
    ) -> None:
        self._relays: dict[str, NostrRelayConnection] = {}
        self.on_event = on_event
        self.on_status = on_status
        self._base_filter = {"kinds": CROWD_KINDS}
        self._lock = threading.Lock()
        for uri in uris or []:
            self.add(uri)

    def add(self, uri: str) -> NostrRelayConnection:
        with self._lock:
            if uri in self._relays:
                return self._relays[uri]
            relay = NostrRelayConnection(
                uri=uri,
                on_event=self.on_event,
                on_status=self.on_status,
            )
            self._relays[uri] = relay
        relay.start()
        relay.subscribe(filters=self._base_filter)
        return relay

    def remove(self, uri: str) -> None:
        with self._lock:
            relay = self._relays.pop(uri, None)
        if relay:
            relay.stop()

    def publish(self, event: dict[str, Any]) -> None:
        with self._lock:
            relays = list(self._relays.values())
        for relay in relays:
            relay.publish(event)

    def publish_to(self, event: dict[str, Any], uris: list[str] | None) -> None:
        """Publish an event only to a subset of relays (used for scoped private tasks)."""
        targets = set(uris or [])
        with self._lock:
            relays = [r for r in self._relays.values() if r.uri in targets or r.name in targets]
        for relay in relays:
            relay.publish(event)

    def subscribe(self, filters: dict[str, Any]) -> None:
        with self._lock:
            relays = list(self._relays.values())
        for relay in relays:
            relay.subscribe(filters=filters)

    def flush(self, timeout: float = 3.0) -> list[str]:
        """Flush every relay's outbound queue and return the URIs that drained."""
        with self._lock:
            relays = list(self._relays.values())
        flushed: list[str] = []
        for relay in relays:
            if relay.flush(timeout):
                flushed.append(relay.uri)
        return flushed

    def connected_uris(self) -> list[str]:
        with self._lock:
            return [r.uri for r in self._relays.values() if r.is_connected()]

    def stop(self) -> None:
        with self._lock:
            relays = list(self._relays.values())
            self._relays.clear()
        for relay in relays:
            relay.stop()
