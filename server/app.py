"""FastAPI application exposing MAVLink telemetry over WebSocket.

Run with `python -m server` (see `server/__main__.py`) from the repo
root, or directly with uvicorn: `uvicorn server.app:app`.

Wiring:
  MavlinkBridge (background thread, blocking pymavlink reads)
      -> on_message callback -> asyncio.Queue (thread-safe handoff)
      -> pump() task drains the queue -> Broadcaster.broadcast()
      -> every connected WebSocket client on /ws/telemetry
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from server.bridge import MavlinkBridge
from server.broadcaster import Broadcaster
from server.config import get_settings

logger = logging.getLogger("webgcs.app")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    broadcaster = Broadcaster()
    stop_event = threading.Event()

    def on_message(message: dict[str, Any]) -> None:
        # Called from the bridge's background thread; hand off to the
        # event loop thread-safely instead of touching asyncio state
        # directly from another thread.
        loop.call_soon_threadsafe(queue.put_nowait, message)

    bridge = MavlinkBridge(
        settings.mavlink_connection,
        on_message,
        reconnect_delay_s=settings.mavlink_reconnect_delay_s,
        read_timeout_s=settings.mavlink_read_timeout_s,
    )
    bridge_thread = threading.Thread(
        target=bridge.run_forever, args=(stop_event,), name="mavlink-bridge", daemon=True
    )

    async def pump() -> None:
        while True:
            message = await queue.get()
            await broadcaster.broadcast(message)

    pump_task = asyncio.create_task(pump())
    bridge_thread.start()

    app.state.broadcaster = broadcaster
    logger.info("bridge started, target=%s", settings.mavlink_connection)

    try:
        yield
    finally:
        stop_event.set()
        pump_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await pump_task
        bridge_thread.join(timeout=5)


app = FastAPI(title="webgcs bridge", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.websocket("/ws/telemetry")
async def ws_telemetry(websocket: WebSocket) -> None:
    broadcaster: Broadcaster = websocket.app.state.broadcaster
    await websocket.accept()
    await broadcaster.connect(websocket)
    try:
        while True:
            # The frontend doesn't send anything meaningful over this
            # socket; receiving is just how we detect a disconnect.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await broadcaster.disconnect(websocket)
