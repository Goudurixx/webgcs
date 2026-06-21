# Architecture (M1 snapshot)

Full architecture write-up (diagram, threading model, message contract
rationale) lands in M4. This is a short interim note covering what M1
actually builds.

## Data flow

```
ArduCopter SITL (Docker, TCP 5760)
        |  MAVLink
        v
MavlinkBridge (server/bridge.py)          <- background OS thread, blocking pymavlink reads
        |  translate() (server/mavlink_codec.py)
        v
asyncio.Queue                              <- thread-safe handoff via loop.call_soon_threadsafe
        |
        v
Broadcaster (server/broadcaster.py)        <- fan-out to N connected clients
        |
        v
WebSocket clients on /ws/telemetry
```

## Why a background thread

`pymavlink`'s `mavutil.mavlink_connection` is a blocking, synchronous
API. Running its read loop inside the asyncio event loop would stall
every other coroutine (including WebSocket sends) while waiting on the
network. Instead, `MavlinkBridge.run_forever` runs on a plain
`threading.Thread`, and the only cross-thread interaction is handing
off already-translated dicts to an `asyncio.Queue` via
`loop.call_soon_threadsafe`.

## Message contract

See the root [`README.md`](../README.md#message-contract-bridge--frontend)
for the exact JSON shapes. `server/mavlink_codec.py` is the single
source of truth for the mapping and is unit-tested against
synthetically constructed MAVLink messages (`tests/test_mavlink_codec.py`)
so the contract can be verified without a live SITL instance.

One deliberate addition beyond the four MAVLink message types named in
the project spec: `GPS_RAW_INT` is also decoded, because the `status`
message's `gps_fix` / `sats` fields don't exist on `SYS_STATUS` or
`HEARTBEAT` — they only exist on `GPS_RAW_INT`.
