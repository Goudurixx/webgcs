"""Unit tests for the WebSocket fan-out (`server.broadcaster.Broadcaster`)."""

from __future__ import annotations

import json

import pytest

from server.broadcaster import Broadcaster


class FakeClient:
    """Minimal stand-in for a `fastapi.WebSocket`: records sent text, can fail on demand."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[str] = []

    async def send_text(self, data: str) -> None:
        if self.fail:
            raise RuntimeError("simulated send failure")
        self.sent.append(data)


@pytest.mark.asyncio
async def test_broadcast_reaches_all_connected_clients() -> None:
    broadcaster = Broadcaster()
    a, b = FakeClient(), FakeClient()
    await broadcaster.connect(a)
    await broadcaster.connect(b)

    await broadcaster.broadcast({"type": "heartbeat", "ts": 1.0})

    assert json.loads(a.sent[0]) == {"type": "heartbeat", "ts": 1.0}
    assert json.loads(b.sent[0]) == {"type": "heartbeat", "ts": 1.0}


@pytest.mark.asyncio
async def test_disconnect_stops_further_delivery() -> None:
    broadcaster = Broadcaster()
    client = FakeClient()
    await broadcaster.connect(client)
    await broadcaster.disconnect(client)

    await broadcaster.broadcast({"type": "heartbeat", "ts": 1.0})

    assert client.sent == []


@pytest.mark.asyncio
async def test_failed_send_drops_client_without_affecting_others() -> None:
    broadcaster = Broadcaster()
    broken = FakeClient(fail=True)
    healthy = FakeClient()
    await broadcaster.connect(broken)
    await broadcaster.connect(healthy)

    await broadcaster.broadcast({"type": "heartbeat", "ts": 1.0})

    assert healthy.sent  # still received the message
    assert broadcaster.client_count == 1  # broken client was deregistered

    # A second broadcast should not error even though `broken` is gone.
    await broadcaster.broadcast({"type": "heartbeat", "ts": 2.0})
    assert len(healthy.sent) == 2


@pytest.mark.asyncio
async def test_client_count_reflects_connections() -> None:
    broadcaster = Broadcaster()
    assert broadcaster.client_count == 0
    client = FakeClient()
    await broadcaster.connect(client)
    assert broadcaster.client_count == 1
    await broadcaster.disconnect(client)
    assert broadcaster.client_count == 0
