"""Minimal in-memory Nostr relay server for local Crowd testing.

This is intentionally small: it persists events in memory only, supports the
subset of NIP-01 filters needed for the OpenPlanter crowd kinds, and lets two
processes on the same machine exchange signed events without external strfry.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from dataclasses import dataclass, field
from typing import Any

try:
    import websockets
except Exception:  # pragma: no cover
    websockets = None  # type: ignore[assignment]

CROWD_KINDS = [31001, 31002, 31003, 31004, 31005, 31006, 31007]

LOGGER = logging.getLogger(__name__)


@dataclass
class _Client:
    ws: Any
    subs: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


class CrowdRelayServer:
    """In-memory WebSocket relay for tests and local federation."""

    def __init__(self, host: str = "127.0.0.1", port: int = 7777) -> None:
        self.host = host
        self.port = port
        self._events: list[dict[str, Any]] = []
        self._clients: list[_Client] = []
        self._lock = asyncio.Lock()
        self._server: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> None:
        if websockets is None:
            raise RuntimeError("websockets library is not installed")
        LOGGER.info("Starting CrowdRelay on ws://%s:%d", self.host, self.port)
        self._server = await websockets.serve(self._handle, self.host, self.port)
        self._loop = asyncio.get_running_loop()

    def start_in_thread(self) -> threading.Thread:
        """Start the relay in a daemon thread and wait until it is listening."""
        started = threading.Event()

        def runner() -> None:
            async def _serve() -> None:
                await self.start()
                started.set()
                while True:
                    await asyncio.sleep(1)

            try:
                asyncio.run(_serve())
            except Exception as exc:
                LOGGER.error("relay server thread exited: %s", exc)

        thread = threading.Thread(target=runner, daemon=True)
        thread.start()
        started.wait(timeout=5)
        return thread

    async def _async_stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    def stop(self) -> None:
        """Stop the server from any thread."""
        if self._server is None:
            return
        if self._loop is not None:
            self._loop.call_soon_threadsafe(
                self._loop.create_task,
                self._async_stop(),
            )
            self._loop.call_soon_threadsafe(
                self._loop.call_later,
                0.2,
                self._loop.stop,
            )
        self._clients.clear()

    def _event_match(self, event: dict[str, Any], filter_: dict[str, Any]) -> bool:
        kinds = filter_.get("kinds")
        if kinds is not None and event.get("kind") not in kinds:
            return False

        ids = filter_.get("ids")
        if ids is not None and event.get("id") not in ids:
            return False

        authors = filter_.get("authors")
        if authors is not None and event.get("pubkey") not in authors:
            return False

        since = filter_.get("since")
        if since is not None and event.get("created_at", 0) < since:
            return False

        until = filter_.get("until")
        if until is not None and event.get("created_at", 0) > until:
            return False

        # Tag filters
        for key, values in filter_.items():
            if key.startswith("#") and len(key) == 2:
                tag_name = key[1]
                event_tags = event.get("tags", [])
                matched = any(
                    len(t) >= 2 and t[0] == tag_name and t[1] in values
                    for t in event_tags
                )
                if not matched:
                    return False

        return True

    async def _handle(self, ws: Any) -> None:
        client = _Client(ws=ws)
        self._clients.append(client)
        try:
            async for raw in ws:
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(msg, list) or not msg:
                    continue
                await self._route(client, msg)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            try:
                self._clients.remove(client)
            except ValueError:
                pass

    def _verify_incoming(self, event: dict[str, Any]) -> bool:
        try:
            from .crowd import NostrEvent, verify_event

            return verify_event(NostrEvent.from_dict(event))
        except Exception as exc:
            LOGGER.debug("relay server verification error: %s", exc)
            return False

    async def _route(self, client: _Client, msg: list[Any]) -> None:
        cmd = msg[0]
        if cmd == "EVENT" and len(msg) == 2:
            event = msg[1]
            ok = "true"
            if not isinstance(event, dict):
                ok = "invalid: event is not an object"
            elif not self._verify_incoming(event):
                ok = "invalid: failed id/signature verification"
            else:
                async with self._lock:
                    self._events.append(event)
                await self._broadcast(event, exclude=client)
            try:
                await client.ws.send(json.dumps(["OK", event.get("id", ""), ok, ""], separators=(",", ":")))
            except Exception:
                pass

        elif cmd == "REQ" and len(msg) >= 3:
            sub_id = msg[1]
            filters = msg[2:]
            if isinstance(filters, dict):
                filters = [filters]
            if isinstance(filters, tuple):
                filters = list(filters)
            client.subs[sub_id] = filters
            async with self._lock:
                events = list(self._events)
            for event in events:
                for filter_ in filters:
                    if self._event_match(event, filter_):
                        await self._send_event(client, sub_id, event)
                        break
            try:
                await client.ws.send(json.dumps(["EOSE", sub_id], separators=(",", ":")))
            except Exception:
                pass

        elif cmd == "CLOSE" and len(msg) >= 2:
            sub_id = msg[1]
            client.subs.pop(sub_id, None)

    async def _send_event(self, client: _Client, sub_id: str, event: dict[str, Any]) -> None:
        try:
            await client.ws.send(json.dumps(["EVENT", sub_id, event], separators=(",", ":")))
        except Exception:
            pass

    async def _broadcast(self, event: dict[str, Any], exclude: _Client | None = None) -> None:
        clients = list(self._clients)
        dead: list[_Client] = []
        for client in clients:
            if client is exclude:
                continue
            for sub_id, filters in client.subs.items():
                for filter_ in filters:
                    if self._event_match(event, filter_):
                        try:
                            await self._send_event(client, sub_id, event)
                        except Exception:
                            dead.append(client)
                        break
        for client in dead:
            try:
                self._clients.remove(client)
            except ValueError:
                pass
