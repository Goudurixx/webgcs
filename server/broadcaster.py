"""Fan-out of JSON telemetry messages to connected WebSocket clients."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Protocol

logger = logging.getLogger("webgcs.broadcaster")


class _SendsJSON(Protocol):
    async def send_text(self, data: str) -> None: ...


class Broadcaster:
    """Tracks connected WebSocket clients and pushes messages to all of them.

    A dropped or slow client never blocks delivery to the others: each
    send is attempted independently and a failure just deregisters that
    one client.
    """

    def __init__(self) -> None:
        self._clients: set[_SendsJSON] = set()
        self._lock = asyncio.Lock()

    async def connect(self, client: _SendsJSON) -> None:
        async with self._lock:
            self._clients.add(client)

    async def disconnect(self, client: _SendsJSON) -> None:
        async with self._lock:
            self._clients.discard(client)

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Serialize `message` once and send it to every connected client."""
        payload = json.dumps(message)
        async with self._lock:
            clients = list(self._clients)

        stale: list[_SendsJSON] = []
        for client in clients:
            try:
                await client.send_text(payload)
            except Exception:  # noqa: BLE001 - any send failure means "drop this client"
                logger.debug("dropping client after failed send", exc_info=True)
                stale.append(client)

        if stale:
            async with self._lock:
                for client in stale:
                    self._clients.discard(client)
