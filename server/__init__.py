"""webgcs bridge: pymavlink -> WebSocket telemetry server.

This package connects to a MAVLink source (typically ArduPilot SITL),
decodes a small set of telemetry messages, and re-emits them as JSON
over a FastAPI WebSocket endpoint using a fixed message contract. See
``server.mavlink_codec`` for the contract and translation logic.
"""

__version__ = "0.1.0"
