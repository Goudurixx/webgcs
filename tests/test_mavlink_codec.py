"""Unit tests for the MAVLink -> JSON contract translation.

Fixtures are real `pymavlink` message objects, constructed directly
(no network, no live SITL) with `pymavlink.dialects.v20.ardupilotmega`.
This is the same message class hierarchy `mavutil.recv_match()` returns
when reading from a live connection, so exercising `translate()`
against these objects is a faithful test of the bridge's decoding
logic.
"""

from __future__ import annotations

import math

from pymavlink.dialects.v20 import ardupilotmega as mavlink2

from server.mavlink_codec import (
    TelemetryState,
    apply_gps_raw_int,
    apply_heartbeat,
    apply_sys_status,
    attitude_message,
    heartbeat_message,
    position_message,
    status_message,
    translate,
)

MAV_MODE_FLAG_SAFETY_ARMED = 128
MAV_MODE_FLAG_CUSTOM_MODE_ENABLED = 1


def make_global_position_int(
    *,
    lat: int = 473_977_418,
    lon: int = 85_455_938,
    alt: int = 50_000,
    relative_alt: int = 20_000,
    hdg: int = 9_000,
) -> mavlink2.MAVLink_global_position_int_message:
    return mavlink2.MAVLink_global_position_int_message(
        time_boot_ms=1_000,
        lat=lat,
        lon=lon,
        alt=alt,
        relative_alt=relative_alt,
        vx=0,
        vy=0,
        vz=0,
        hdg=hdg,
    )


def make_attitude(
    *, roll: float = 0.1, pitch: float = -0.2, yaw: float = 1.0
) -> mavlink2.MAVLink_attitude_message:
    return mavlink2.MAVLink_attitude_message(
        time_boot_ms=1_000,
        roll=roll,
        pitch=pitch,
        yaw=yaw,
        rollspeed=0.0,
        pitchspeed=0.0,
        yawspeed=0.0,
    )


def make_heartbeat(
    *, custom_mode: int = 4, armed: bool = True
) -> mavlink2.MAVLink_heartbeat_message:
    base_mode = MAV_MODE_FLAG_CUSTOM_MODE_ENABLED
    if armed:
        base_mode |= MAV_MODE_FLAG_SAFETY_ARMED
    return mavlink2.MAVLink_heartbeat_message(
        type=mavlink2.MAV_TYPE_QUADROTOR,
        autopilot=mavlink2.MAV_AUTOPILOT_ARDUPILOTMEGA,
        base_mode=base_mode,
        custom_mode=custom_mode,
        system_status=mavlink2.MAV_STATE_ACTIVE,
        mavlink_version=3,
    )


def make_sys_status(
    *, voltage_battery: int = 12_345, battery_remaining: int = 77
) -> mavlink2.MAVLink_sys_status_message:
    return mavlink2.MAVLink_sys_status_message(
        onboard_control_sensors_present=0,
        onboard_control_sensors_enabled=0,
        onboard_control_sensors_health=0,
        load=0,
        voltage_battery=voltage_battery,
        current_battery=500,
        battery_remaining=battery_remaining,
        drop_rate_comm=0,
        errors_comm=0,
        errors_count1=0,
        errors_count2=0,
        errors_count3=0,
        errors_count4=0,
    )


def make_gps_raw_int(
    *, fix_type: int = 3, satellites_visible: int = 11
) -> mavlink2.MAVLink_gps_raw_int_message:
    return mavlink2.MAVLink_gps_raw_int_message(
        time_usec=0,
        fix_type=fix_type,
        lat=473_977_418,
        lon=85_455_938,
        alt=50_000,
        eph=100,
        epv=100,
        vel=0,
        cog=0,
        satellites_visible=satellites_visible,
    )


# --- position -----------------------------------------------------------


def test_position_message_maps_fields() -> None:
    msg = make_global_position_int()
    out = position_message(msg, ts=123.5)

    assert out == {
        "type": "position",
        "lat": 47.3977418,
        "lon": 8.5455938,
        "alt_m": 20.0,
        "heading_deg": 90.0,
        "ts": 123.5,
    }


def test_position_message_uses_relative_altitude_not_amsl() -> None:
    msg = make_global_position_int(alt=99_000, relative_alt=15_500)
    out = position_message(msg, ts=0.0)
    assert out["alt_m"] == 15.5


def test_position_message_unknown_heading_maps_to_zero() -> None:
    msg = make_global_position_int(hdg=65535)
    out = position_message(msg, ts=0.0)
    assert out["heading_deg"] == 0.0


# --- attitude -------------------------------------------------------------


def test_attitude_message_converts_radians_to_degrees() -> None:
    msg = make_attitude(roll=math.pi / 2, pitch=-math.pi / 4, yaw=math.pi)
    out = attitude_message(msg, ts=42.0)

    assert out["type"] == "attitude"
    assert out["roll_deg"] == 90.0
    assert out["pitch_deg"] == -45.0
    assert out["yaw_deg"] == 180.0
    assert out["ts"] == 42.0


# --- heartbeat --------------------------------------------------------------


def test_heartbeat_message_is_just_a_timestamp() -> None:
    assert heartbeat_message(ts=7.0) == {"type": "heartbeat", "ts": 7.0}


# --- state updates ----------------------------------------------------------


def test_apply_heartbeat_sets_mode_and_armed() -> None:
    state = TelemetryState()
    apply_heartbeat(state, make_heartbeat(custom_mode=4, armed=True))  # 4 == GUIDED
    assert state.mode == "GUIDED"
    assert state.armed is True


def test_apply_heartbeat_disarmed() -> None:
    state = TelemetryState()
    apply_heartbeat(state, make_heartbeat(custom_mode=0, armed=False))  # 0 == STABILIZE
    assert state.mode == "STABILIZE"
    assert state.armed is False


def test_apply_heartbeat_unknown_custom_mode_falls_back_to_generic_name() -> None:
    state = TelemetryState()
    apply_heartbeat(state, make_heartbeat(custom_mode=999))
    assert state.mode == "MODE_999"


def test_apply_sys_status_updates_battery_and_voltage() -> None:
    state = TelemetryState()
    apply_sys_status(state, make_sys_status(voltage_battery=16_800, battery_remaining=88))
    assert state.voltage_v == 16.8
    assert state.battery_pct == 88


def test_apply_sys_status_ignores_unknown_sentinels() -> None:
    state = TelemetryState(battery_pct=55, voltage_v=12.1)
    apply_sys_status(state, make_sys_status(voltage_battery=65535, battery_remaining=-1))
    # Unknown-value sentinels must not clobber the last known good reading.
    assert state.battery_pct == 55
    assert state.voltage_v == 12.1


def test_apply_gps_raw_int_updates_fix_and_sats() -> None:
    state = TelemetryState()
    apply_gps_raw_int(state, make_gps_raw_int(fix_type=3, satellites_visible=14))
    assert state.gps_fix == 3
    assert state.sats == 14


# --- status assembly ---------------------------------------------------------


def test_status_message_reflects_state() -> None:
    state = TelemetryState(
        battery_pct=42, voltage_v=11.1, mode="LOITER", armed=True, gps_fix=3, sats=9
    )
    out = status_message(state, ts=5.0)
    assert out == {
        "type": "status",
        "battery_pct": 42,
        "voltage_v": 11.1,
        "mode": "LOITER",
        "armed": True,
        "gps_fix": 3,
        "sats": 9,
        "ts": 5.0,
    }


# --- translate() dispatch -----------------------------------------------------


def test_translate_global_position_int_returns_position_only() -> None:
    state = TelemetryState()
    out = translate(make_global_position_int(), state, ts=1.0)
    assert [m["type"] for m in out] == ["position"]


def test_translate_attitude_returns_attitude_only() -> None:
    state = TelemetryState()
    out = translate(make_attitude(), state, ts=1.0)
    assert [m["type"] for m in out] == ["attitude"]


def test_translate_heartbeat_returns_heartbeat_then_status() -> None:
    state = TelemetryState()
    out = translate(make_heartbeat(custom_mode=4, armed=True), state, ts=1.0)

    assert [m["type"] for m in out] == ["heartbeat", "status"]
    assert out[1]["mode"] == "GUIDED"
    assert out[1]["armed"] is True


def test_translate_sys_status_returns_status_only() -> None:
    state = TelemetryState()
    out = translate(make_sys_status(), state, ts=1.0)
    assert [m["type"] for m in out] == ["status"]


def test_translate_gps_raw_int_returns_status_only() -> None:
    state = TelemetryState()
    out = translate(make_gps_raw_int(), state, ts=1.0)
    assert [m["type"] for m in out] == ["status"]


def test_translate_unhandled_message_type_returns_empty_list() -> None:
    state = TelemetryState()
    system_time = mavlink2.MAVLink_system_time_message(time_unix_usec=0, time_boot_ms=0)
    assert translate(system_time, state, ts=1.0) == []


def test_translate_merges_state_across_out_of_order_messages() -> None:
    """Simulates a realistic MAVLink stream: fields for "status" arrive
    on three different message types, interleaved with position/attitude
    updates that don't affect status at all.
    """
    state = TelemetryState()

    translate(make_heartbeat(custom_mode=5, armed=False), state, ts=1.0)  # 5 == LOITER
    translate(make_global_position_int(), state, ts=1.1)
    translate(make_sys_status(voltage_battery=12_000, battery_remaining=60), state, ts=1.2)
    final = translate(make_gps_raw_int(fix_type=3, satellites_visible=12), state, ts=1.3)

    assert [m["type"] for m in final] == ["status"]
    status = final[0]
    assert status["mode"] == "LOITER"
    assert status["armed"] is False
    assert status["voltage_v"] == 12.0
    assert status["battery_pct"] == 60
    assert status["gps_fix"] == 3
    assert status["sats"] == 12
