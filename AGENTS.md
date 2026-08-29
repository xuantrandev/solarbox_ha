# AGENTS.md

Home Assistant custom component (`solarproject`) that connects to a **solardongleweb** WebSocket server to expose one solar dongle (inverter + BMS) as HA entities. Root `README.md` is a stub — the authoritative docs are `custom_components/solarproject/README.md`.

## No local dev environment — verification is via Docker

- There is **no** pytest/pyproject/lint/CI. The host Python lacks `homeassistant` and `aiohttp`, so component code cannot be imported or run locally. Do not attempt local syntax/import checks.
- Test instance: `docker compose -f ha_test/docker-compose.yaml up -d` — container `homeassistant-test`, image `homeassistant:stable` (pinned in `data/ha1/.HA_VERSION` = 2025.11.3), config dir `data/ha1` mounted at `/config`, web UI on host port **8126**.
- To test a change: `cp -r custom_components/solarproject data/ha1/custom_components/solarproject`, then reload the integration (Developer Tools → YAML → Reload) or restart the container. Check `data/ha1/home-assistant.log` for errors/warnings.
- `data/` is gitignored (live HA config incl. DB/secrets); `ha_test/docker-compose.yaml` is committed.

## Layout

- `custom_components/solarproject/` — the integration, one config entry per dongle:
  - `coordinator.py` — custom WebSocket worker (not a `DataUpdateCoordinator`): connects to `/ws/<deviceId>`, parses pushed messages into a flat latest-state dict, notifies listeners, reconnect backoff 10→60 s (server rate-limits WS to 20/min per IP — never lower `WS_RECONNECT_MIN`), optional `requestDataUpdate` loop (fast-data mode, min 5 s).
  - `const.py` — all field metadata (`SensorDef` incl. `scale`); add/rename sensor fields here.
  - `sensor.py`, `binary_sensor.py` — entities mirror keys of the coordinator's state dict; no polling.
- Data flow is push-only over WebSocket; entities stay "unknown" until their field first arrives. No auth on the server side.

## Conventions that matter

- Sensor names are verbatim from the dongle's HA firmware yaml (`solardongle/release_luxbleha.yaml` + `platform/base_luxha.yaml`): `Ivt` prefix for inverter, lowercase `bms{n}` for BMS, fixed names like `Dongle SN`, `IP Address`, `Wifi Signal`. Do not "clean up" these names.
- BMS raw values need scaling from `SensorDef.scale` (0.1 V/A/°C, 0.001 Ah/V); inverter values pass through as-is.
- Config flow validates by actually opening a WS to the server (`config_flow.py:_validate_connection`).

## Known issues (from `data/ha1/home-assistant.log`)

- `sensor.py:67` `await async_add_entities(...)` — `async_add_entities` is a plain callback, not a coroutine; BMS cell creation crashes with `TypeError: object NoneType can't be used in 'await' expression` whenever a BMS with cells reports data.
- Daily energy sensors (`eex`, `pvtd`, `ltd`, `ech`, `edch`, `eim` in `const.py`) use `SensorStateClass.MEASUREMENT` with energy device class → HA logs state-class warnings; `STATISTIC_FIELDS` totals already use `TOTAL_INCREASING`.
- Removing a BMS slot does not remove already-created cell sensors; requires reload.