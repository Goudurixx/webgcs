"""Runtime configuration for the telemetry bridge.

All settings are read from environment variables so the server can be
configured the same way in a shell, a Docker container, or CI without
code changes. Defaults target a locally running ArduCopter SITL
instance listening for MAVLink on TCP port 5760.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_str(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return int(raw)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return float(raw)


@dataclass(frozen=True)
class Settings:
    """Immutable snapshot of the bridge's runtime configuration."""

    # MAVLink connection string, in pymavlink's `mavutil.mavlink_connection`
    # format. The default matches the `sim/docker-compose.yml` SITL service,
    # which exposes MAVLink on TCP 5760.
    mavlink_connection: str = "tcp:127.0.0.1:5760"

    # Seconds to wait for a MAVLink connection/heartbeat before retrying.
    mavlink_reconnect_delay_s: float = 2.0

    # Seconds to wait for a single MAVLink message before looping again
    # (allows the reader thread to notice shutdown requests promptly).
    mavlink_read_timeout_s: float = 1.0

    # HTTP/WebSocket server bind address.
    server_host: str = "0.0.0.0"
    server_port: int = 8000


def get_settings() -> Settings:
    """Build a `Settings` instance from the current environment."""
    return Settings(
        mavlink_connection=_env_str("WEBGCS_MAVLINK_CONNECTION", "tcp:127.0.0.1:5760"),
        mavlink_reconnect_delay_s=_env_float("WEBGCS_MAVLINK_RECONNECT_DELAY_S", 2.0),
        mavlink_read_timeout_s=_env_float("WEBGCS_MAVLINK_READ_TIMEOUT_S", 1.0),
        server_host=_env_str("WEBGCS_HOST", "0.0.0.0"),
        server_port=_env_int("WEBGCS_PORT", 8000),
    )
