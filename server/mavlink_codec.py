"""MAVLink message -> JSON contract translation.

This module is the single source of truth for the bridge->frontend
message contract documented in the project README:

    {"type":"position","lat":0,"lon":0,"alt_m":0,"heading_deg":0,"ts":0}
    {"type":"attitude","roll_deg":0,"pitch_deg":0,"yaw_deg":0,"ts":0}
    {"type":"status","battery_pct":0,"voltage_v":0,"mode":"GUIDED","armed":false,"gps_fix":3,"sats":10,"ts":0}
    {"type":"heartbeat","ts":0}

Everything here is pure and synchronous on purpose: functions take a
decoded MAVLink message object (as returned by pymavlink, or an
equivalent constructed directly for tests) plus a wall-clock timestamp,
and return plain dicts that are ready to `json.dumps`. No sockets, no
asyncio, no I/O -- which is what makes this module unit-testable with
synthetic fixture messages instead of a live SITL instance.

Four MAVLink message types drive the contract:
  - GLOBAL_POSITION_INT -> "position"
  - ATTITUDE             -> "attitude"
  - HEARTBEAT            -> "heartbeat" (+ refreshed "status", since mode
                            and armed state live in this message)
  - SYS_STATUS           -> refreshed "status" (battery/voltage)

One additional message, GPS_RAW_INT, is decoded too: the contract's
`status.gps_fix` / `status.sats` fields don't exist anywhere in
SYS_STATUS or HEARTBEAT, they come from GPS_RAW_INT. This is a
deliberate, documented addition to the message set named in the spec,
not a deviation from the JSON contract itself.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pymavlink import mavutil

# MAV_MODE_FLAG_SAFETY_ARMED, see MAVLink common.xml. Re-declared as a
# plain int so this module doesn't depend on which dialect submodule the
# caller imported the message classes from.
_MAV_MODE_FLAG_SAFETY_ARMED = 128

# MAVLink's "value not available" sentinels.
_UNKNOWN_HEADING_CDEG = 65535
_UNKNOWN_VOLTAGE_MV = 65535
_UNKNOWN_BATTERY_PCT = -1
_UNKNOWN_SATS = 255

# ArduCopter custom_mode -> mode name. The stack is fixed to ArduCopter
# SITL (see project README), so this is the correct mapping table; a
# Plane/Rover build would need mode_mapping_apm / mode_mapping_rover
# instead.
_MODE_MAP: dict[int, str] = mavutil.mode_mapping_acm


def _mode_name(custom_mode: int) -> str:
    return _MODE_MAP.get(custom_mode, f"MODE_{custom_mode}")


def _is_armed(base_mode: int) -> bool:
    return bool(base_mode & _MAV_MODE_FLAG_SAFETY_ARMED)


@dataclass
class TelemetryState:
    """Cached last-known values used to assemble the "status" message.

    "status" is a merge of fields that arrive on three different MAVLink
    message types (HEARTBEAT, SYS_STATUS, GPS_RAW_INT), each at its own
    rate. Rather than waiting for all three before emitting anything,
    the bridge keeps the latest known value of each field here and
    re-emits a full "status" message whenever any one of them updates.
    """

    battery_pct: int = 0
    voltage_v: float = 0.0
    mode: str = "UNKNOWN"
    armed: bool = False
    gps_fix: int = 0
    sats: int = 0


def position_message(msg: Any, ts: float) -> dict[str, Any]:
    """Translate a GLOBAL_POSITION_INT message to a "position" contract message.

    Altitude is reported as height above the vehicle's home/takeoff point
    (`relative_alt`), which is what a GCS operator typically wants on a
    live HUD, rather than AMSL altitude.
    """
    hdg = msg.hdg
    heading_deg = 0.0 if hdg == _UNKNOWN_HEADING_CDEG else round(hdg / 100.0, 2)
    return {
        "type": "position",
        "lat": msg.lat / 1e7,
        "lon": msg.lon / 1e7,
        "alt_m": round(msg.relative_alt / 1000.0, 2),
        "heading_deg": heading_deg,
        "ts": ts,
    }


def attitude_message(msg: Any, ts: float) -> dict[str, Any]:
    """Translate an ATTITUDE message (radians) to an "attitude" contract message (degrees)."""
    return {
        "type": "attitude",
        "roll_deg": round(math.degrees(msg.roll), 2),
        "pitch_deg": round(math.degrees(msg.pitch), 2),
        "yaw_deg": round(math.degrees(msg.yaw), 2),
        "ts": ts,
    }


def heartbeat_message(ts: float) -> dict[str, Any]:
    """Build the "heartbeat" contract message.

    This is intentionally just a timestamp: its purpose is a frontend
    connection watchdog, not payload delivery.
    """
    return {"type": "heartbeat", "ts": ts}


def status_message(state: TelemetryState, ts: float) -> dict[str, Any]:
    """Assemble the "status" contract message from cached state."""
    return {
        "type": "status",
        "battery_pct": state.battery_pct,
        "voltage_v": state.voltage_v,
        "mode": state.mode,
        "armed": state.armed,
        "gps_fix": state.gps_fix,
        "sats": state.sats,
        "ts": ts,
    }


def apply_heartbeat(state: TelemetryState, msg: Any) -> None:
    """Update cached mode/armed state from a HEARTBEAT message."""
    state.mode = _mode_name(msg.custom_mode)
    state.armed = _is_armed(msg.base_mode)


def apply_sys_status(state: TelemetryState, msg: Any) -> None:
    """Update cached battery state from a SYS_STATUS message.

    Unknown-value sentinels (see MAVLink common.xml) are left as-is
    rather than overwriting the last known good reading.
    """
    if msg.battery_remaining != _UNKNOWN_BATTERY_PCT:
        state.battery_pct = msg.battery_remaining
    if msg.voltage_battery != _UNKNOWN_VOLTAGE_MV:
        state.voltage_v = round(msg.voltage_battery / 1000.0, 3)


def apply_gps_raw_int(state: TelemetryState, msg: Any) -> None:
    """Update cached GPS fix/satellite count from a GPS_RAW_INT message."""
    state.gps_fix = msg.fix_type
    state.sats = msg.satellites_visible


# Message type name -> handler that mutates `TelemetryState` in place.
_STATE_UPDATERS: dict[str, Callable[[TelemetryState, Any], None]] = {
    "HEARTBEAT": apply_heartbeat,
    "SYS_STATUS": apply_sys_status,
    "GPS_RAW_INT": apply_gps_raw_int,
}

# Message type name -> whether it should also emit a refreshed "status"
# message once its state update has been applied.
_EMITS_STATUS = {"HEARTBEAT", "SYS_STATUS", "GPS_RAW_INT"}


def translate(msg: Any, state: TelemetryState, ts: float) -> list[dict[str, Any]]:
    """Translate one decoded MAVLink message into zero or more contract messages.

    `state` is mutated in place for message types that carry fields used
    by the "status" message (HEARTBEAT, SYS_STATUS, GPS_RAW_INT), so the
    caller should keep one `TelemetryState` per MAVLink connection and
    feed every relevant message through this function in arrival order.
    """
    msg_type = msg.get_type()

    if msg_type == "GLOBAL_POSITION_INT":
        return [position_message(msg, ts)]

    if msg_type == "ATTITUDE":
        return [attitude_message(msg, ts)]

    updater = _STATE_UPDATERS.get(msg_type)
    if updater is None:
        return []

    updater(state, msg)
    out = []
    if msg_type == "HEARTBEAT":
        out.append(heartbeat_message(ts))
    if msg_type in _EMITS_STATUS:
        out.append(status_message(state, ts))
    return out
