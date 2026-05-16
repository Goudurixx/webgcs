"""Background MAVLink reader.

Connects to a MAVLink source via pymavlink, decodes the message types
consumed by `server.mavlink_codec`, and hands translated JSON-ready
dicts to a callback. Runs in a plain OS thread because pymavlink's
`mavutil.mavlink_connection` is a blocking, synchronous API; keeping it
off the asyncio event loop is what lets the WebSocket server stay
responsive while waiting on the network.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from pymavlink import mavutil

from server.mavlink_codec import TelemetryState, translate

logger = logging.getLogger("webgcs.bridge")

# MAVLink message types this bridge understands; everything else on the
# connection is filtered out by `recv_match`.
_HANDLED_MESSAGE_TYPES = (
    "GLOBAL_POSITION_INT",
    "ATTITUDE",
    "HEARTBEAT",
    "SYS_STATUS",
    "GPS_RAW_INT",
)

OnMessage = Callable[[dict[str, Any]], None]


class MavlinkBridge:
    """Reads MAVLink telemetry and emits contract JSON via a callback."""

    def __init__(
        self,
        connection_string: str,
        on_message: OnMessage,
        *,
        reconnect_delay_s: float = 2.0,
        read_timeout_s: float = 1.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._connection_string = connection_string
        self._on_message = on_message
        self._reconnect_delay_s = reconnect_delay_s
        self._read_timeout_s = read_timeout_s
        self._clock = clock
        self._state = TelemetryState()

    def run_forever(self, stop_event: threading.Event) -> None:
        """Connect and stream messages until `stop_event` is set.

        Reconnects automatically (after `reconnect_delay_s`) if the
        connection drops or fails, so a bridge started before SITL is up
        will keep retrying instead of exiting.
        """
        while not stop_event.is_set():
            try:
                self._run_once(stop_event)
            except Exception:  # noqa: BLE001 - keep the bridge alive across any I/O error
                logger.exception(
                    "MAVLink connection error, retrying in %.1fs", self._reconnect_delay_s
                )
                stop_event.wait(self._reconnect_delay_s)

    def _run_once(self, stop_event: threading.Event) -> None:
        logger.info("connecting to MAVLink source %s", self._connection_string)
        conn = mavutil.mavlink_connection(self._connection_string)
        try:
            conn.wait_heartbeat(timeout=10)
            logger.info(
                "MAVLink heartbeat received (system %d, component %d)",
                conn.target_system,
                conn.target_component,
            )
            self._request_data_streams(conn)

            while not stop_event.is_set():
                msg = conn.recv_match(
                    type=_HANDLED_MESSAGE_TYPES, blocking=True, timeout=self._read_timeout_s
                )
                if msg is None:
                    continue
                for out in translate(msg, self._state, self._clock()):
                    self._on_message(out)
        finally:
            conn.close()

    @staticmethod
    def _request_data_streams(conn: Any) -> None:
        """Ask the autopilot to stream telemetry at a usable rate.

        ArduCopter SITL streams some messages by default, but explicitly
        requesting `MAV_DATA_STREAM_ALL` makes the bridge behave
        correctly against any MAVLink source that waits to be asked.
        """
        conn.mav.request_data_stream_send(
            conn.target_system,
            conn.target_component,
            mavutil.mavlink.MAV_DATA_STREAM_ALL,
            4,  # Hz
            1,  # start streaming
        )
