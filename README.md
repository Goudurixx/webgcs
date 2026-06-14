# webgcs

A minimal, browser-based ground control station for MAVLink drones.
`webgcs` connects to an ArduPilot SITL simulated drone, streams its
telemetry over a WebSocket in a small fixed JSON contract, and (from
M2 onward) renders live position, attitude, and status on a map with a
HUD — no proprietary GCS, no native app, just a Python bridge and a
browser tab.

## Status

This repo is built milestone-by-milestone. Currently implemented:

- [x] **M1 — Sim + bridge**: ArduCopter SITL via Docker Compose, and a
  Python (`pymavlink` + FastAPI) bridge that decodes MAVLink and
  re-emits the JSON contract below over `/ws/telemetry`.
- [ ] M2 — MapLibre map + telemetry side panel
- [ ] M3 — Artificial horizon / compass HUD, dark theme
- [ ] M4 — Polish, demo GIF, architecture write-up

See [`docs/architecture.md`](docs/architecture.md) for the current
(M1) data-flow notes.

## Stack

- **SITL**: `ardupilot/ardupilot` Docker image (ArduCopter), MAVLink over TCP 5760
- **Bridge**: Python 3.12, `pymavlink`, FastAPI WebSocket endpoint at `/ws/telemetry`, JSON messages
- **Frontend** *(from M2)*: Vite + TypeScript, MapLibre GL JS (OSM tiles), plain CSS
- **CI**: GitHub Actions — lint (`ruff`) + typecheck (`mypy`) + bridge unit tests (`pytest`)

## Message contract (bridge → frontend)

```json
{"type":"position","lat":0,"lon":0,"alt_m":0,"heading_deg":0,"ts":0}
{"type":"attitude","roll_deg":0,"pitch_deg":0,"yaw_deg":0,"ts":0}
{"type":"status","battery_pct":0,"voltage_v":0,"mode":"GUIDED","armed":false,"gps_fix":3,"sats":10,"ts":0}
{"type":"heartbeat","ts":0}
```

`alt_m` is height above the vehicle's home/takeoff point (MAVLink
`GLOBAL_POSITION_INT.relative_alt`), not AMSL altitude. `ts` is the
bridge's wall-clock time (seconds, `time.time()`) at translation, not
the autopilot's boot-relative clock — the frontend heartbeat watchdog
and any client-side latency measurement depend on that being a real
timestamp. The full mapping lives in
[`server/mavlink_codec.py`](server/mavlink_codec.py) and is unit-tested
in [`tests/test_mavlink_codec.py`](tests/test_mavlink_codec.py).

## Quickstart

```bash
# 1. Start ArduCopter SITL (requires Docker)
cd sim && docker compose up

# 2. In another terminal, start the bridge (requires Python 3.12 + deps below)
cd .. && python -m server

# 3. In a third terminal, watch live telemetry JSON
websocat ws://localhost:8000/ws/telemetry
```

Install the bridge's dependencies first:

```bash
pip install -r requirements.txt
```

Once SITL has booted, arm and fly it from the SITL console
(`docker compose attach ardupilot-sitl`, or any MAVLink-capable console
attached to the same connection):

```
mode guided
arm throttle
takeoff 20
```

`websocat` should now be printing a live stream of `position`,
`attitude`, `status`, and `heartbeat` JSON lines.

No `websocat`? A one-off Python client works too (`pip install websockets`):

```bash
python -c "
import asyncio, websockets
async def main():
    async with websockets.connect('ws://localhost:8000/ws/telemetry') as ws:
        async for message in ws:
            print(message)
asyncio.run(main())
"
```

### Configuration

The bridge reads its MAVLink connection string and bind address from
environment variables (see [`server/config.py`](server/config.py)):

| Variable                          | Default              | Meaning                              |
| ---------------------------------- | --------------------- | ------------------------------------- |
| `WEBGCS_MAVLINK_CONNECTION`        | `tcp:127.0.0.1:5760`  | pymavlink connection string           |
| `WEBGCS_MAVLINK_RECONNECT_DELAY_S` | `2.0`                 | Delay before retrying a dropped link  |
| `WEBGCS_MAVLINK_READ_TIMEOUT_S`    | `1.0`                 | Per-read timeout in the bridge thread |
| `WEBGCS_HOST`                      | `0.0.0.0`             | HTTP/WebSocket bind address           |
| `WEBGCS_PORT`                      | `8000`                | HTTP/WebSocket bind port              |

## Running the tests

The bridge's MAVLink → JSON translation, WebSocket fan-out, and full
`/ws/telemetry` wiring are unit-tested using synthetic MAVLink messages
constructed directly with `pymavlink` — no Docker or live SITL
required to run the test suite:

```bash
pip install -r requirements-dev.txt
pytest -v
```

Lint and type-check the same way CI does:

```bash
ruff check server tests
mypy server
```

## Repo structure

```
webgcs/
├── server/          # Python bridge: pymavlink -> WebSocket (FastAPI + uvicorn)
├── web/             # Frontend: Vite + TypeScript, MapLibre GL (M2+)
├── sim/             # Docker Compose for ArduPilot SITL
├── docs/            # architecture.md, demo.gif (M4)
├── tests/           # pytest unit tests for the bridge
└── README.md
```

## License

MIT — see [`LICENSE`](LICENSE).
