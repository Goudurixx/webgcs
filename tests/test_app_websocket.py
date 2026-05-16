"""End-to-end check of the /ws/telemetry contract without a live SITL.

This exercises the full wiring described in `server/app.py` -- a
background "bridge" thread pushing messages through an asyncio queue to
every connected WebSocket client -- by swapping in a fake bridge that
emits a canned, known sequence of contract messages instead of reading
real MAVLink. It's the closest thing to the M1 "done" criterion
(`websocat ws://localhost:8000/ws/telemetry` prints live JSON) that can
run in CI without Docker or ArduPilot SITL.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient

import server.app as app_module

CANNED_MESSAGES: list[dict[str, Any]] = [
    {"type": "heartbeat", "ts": 1.0},
    {
        "type": "position",
        "lat": 47.3977418,
        "lon": 8.5455938,
        "alt_m": 20.0,
        "heading_deg": 90.0,
        "ts": 1.1,
    },
    {"type": "attitude", "roll_deg": 1.0, "pitch_deg": -2.0, "yaw_deg": 180.0, "ts": 1.2},
    {
        "type": "status",
        "battery_pct": 88,
        "voltage_v": 16.8,
        "mode": "GUIDED",
        "armed": True,
        "gps_fix": 3,
        "sats": 12,
        "ts": 1.3,
    },
]


class FakeBridge:
    """Drop-in replacement for `MavlinkBridge` used only in this test.

    Same constructor signature and `run_forever(stop_event)` contract,
    but emits `CANNED_MESSAGES` immediately instead of connecting to a
    real MAVLink source.
    """

    def __init__(
        self,
        connection_string: str,
        on_message: Callable[[dict[str, Any]], None],
        *,
        reconnect_delay_s: float = 2.0,
        read_timeout_s: float = 1.0,
    ) -> None:
        self._on_message = on_message

    def run_forever(self, stop_event: threading.Event) -> None:
        # Give the test a moment to open its WebSocket connection(s)
        # before anything is broadcast -- `Broadcaster.broadcast()` only
        # reaches clients that are already connected, same as it would
        # against a real, continuously-streaming bridge.
        time.sleep(0.2)
        for message in CANNED_MESSAGES:
            self._on_message(message)
        # Keep the thread alive (like the real bridge would) until told
        # to stop, so `bridge_thread.join()` in the app's shutdown path
        # behaves the same way it would against a real connection.
        stop_event.wait()


def test_ws_telemetry_streams_contract_messages(monkeypatch) -> None:
    monkeypatch.setattr(app_module, "MavlinkBridge", FakeBridge)

    with TestClient(app_module.app) as client:
        with client.websocket_connect("/ws/telemetry") as ws:
            received = [ws.receive_json() for _ in CANNED_MESSAGES]

    assert received == CANNED_MESSAGES
    # Every message must carry the "type" discriminator the frontend
    # switches on, and a "ts" field for the heartbeat watchdog / display.
    for message in received:
        assert "type" in message
        assert "ts" in message


def test_healthz() -> None:
    with TestClient(app_module.app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_multiple_clients_all_receive_the_same_stream(monkeypatch) -> None:
    monkeypatch.setattr(app_module, "MavlinkBridge", FakeBridge)

    with TestClient(app_module.app) as client:
        with client.websocket_connect("/ws/telemetry") as ws_a, client.websocket_connect(
            "/ws/telemetry"
        ) as ws_b:
            received_a = [ws_a.receive_json() for _ in CANNED_MESSAGES]
            received_b = [ws_b.receive_json() for _ in CANNED_MESSAGES]

    assert received_a == CANNED_MESSAGES
    assert received_b == CANNED_MESSAGES
