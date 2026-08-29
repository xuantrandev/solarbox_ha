# SolarProject Home Assistant Integration

Home Assistant custom component that connects to a **solardongleweb** server
and automatically creates all entities for a solar dongle (inverter + BMS +
status).

## Features

- **Config flow**: enter the solardongleweb server URL and the dongle device
  ID (`dg-xxxxxx`, e.g. `dg-abc123`); the connection is validated before
  saving. Add one integration entry per dongle.
- **Real-time data**: connects to the server's WebSocket endpoint
  (`/ws/<deviceId>`) — the server pushes data as it arrives, no polling.
- **Fast data refresh**: by default the component sends a
  `requestDataUpdate` to the server every **5 seconds**, which keeps the
  dongle in fast-data mode so all sensors update about every 5 s.
- **Auto-reconnect** with exponential backoff (10 s → 60 s, stays within the
  server's 20 connections/min/IP limit).
- **All read-only entities** are created automatically:

| Group | Entities |
|---|---|
| Inverter live | Ivt PV1-3 Voltage/Power (vdc1-3, pdc1-3), Ivt Battery Voltage/SOC/Power/Current (vbat, soc, pbat, bcur), Ivt Grid Voltage/Frequency/Power per phase (vgr, fgr, pgr, vgr1-3, fgr1-3, pgr1-3), Ivt Load Power per phase (pl, pl1-3), Ivt Inverter Power (po) |
| Daily energy | Ivt PV Today / Load Today / Battery Charge Today / Battery Discharge Today / Grid Import Today / Grid Export Today (pvtd, ltd, ech, edch, eim, eex) |
| Lifetime totals | Ivt PV/Load/Grid Import/Grid Export/Battery Charge/Battery Discharge Total (pvall, lall, imall, exall, chgall, dchgall) + Ivt Max Charge/Discharge Power (mxchg, mxdchg) |
| Temperatures | Ivt DC Temp, Ivt AC Temp (dctemp, actemp) |
| BMS slots 1-3 | bms1/bms2/bms3 state of charge, total voltage, current, power, capacity remaining, charging cycles, temperature sensor 1-5, power tube temperature, cell voltage 1-N (dynamic), BMS{n} MAC, bms{n} charging/discharging, bms{n} enable bluetooth connection |
| Status | Online, Lux Cloud, Wifi Signal (dBm), Dongle SN, IP Address, Firmware Version, device info |

**Sensor names follow the dongle HA firmware variant**
(`solardongle/release_luxbleha.yaml` + `platform/base_luxha.yaml`), so entities
match the naming used when the dongle publishes MQTT discovery directly to HA:
inverter sensors use the `Ivt` prefix (`Ivt PV1 Voltage`, `Ivt Battery SOC`),
BMS sensors use lowercase `bms{n}` (`bms1 total voltage`,
`bms1 state of charge`, `bms1 cell voltage 3`), and fixed names like
`Dongle SN`, `IP Address`, `Wifi Signal` are kept verbatim.

## Installation

1. Copy this `custom_components/solarproject/` directory into your Home
   Assistant `config/custom_components/` directory:

   ```bash
   cp -r custom_components/solarproject /path/to/homeassistant/config/custom_components/
   ```
   ```bash
   cp -r custom_components/solarproject data/ha1/custom_components/solarproject
   ``` 
2. Restart Home Assistant (or reload it with Developer Tools → YAML → Reload).

3. Go to **Settings → Devices & Services → Add Integration → solarbox.uk
   devices** and enter:
   - **Server URL**: `https://ivbms.solarbox.uk` (prefilled; change it if your
     solardongleweb server is elsewhere)
   - **Device ID**: e.g. `dg-abc123`
   - **Device name**: optional; defaults to the device ID
   - **Sensor prefix**: optional; controls entity IDs — entities are created
     as `sensor.<prefix>_<sensor name>` instead of
     `sensor.<device_id>_<sensor name>`. Defaults to the device ID.

Repeat for each dongle you want to monitor.

> Changing the sensor prefix later (options flow) creates entities with new
> IDs; the old ones stay in the entity registry but stop updating — remove
> them manually if you no longer need them.

## How the fast-data refresh works

Every 5 seconds the component sends
`{"type":"requestDataUpdate","deviceId":"dg-xxxxxx"}` over the WebSocket. The
server publishes `ON` to the dongle's `switch/fastdata/command`, which puts
the dongle in fast mode (its internal 10 s auto-off timer keeps being reset,
so it stays in fast mode as long as the component is connected) and the
dongle pushes fresh data roughly every 5 s.

### Trade-offs / notes

- The dongle stays in **fast mode continuously** (faster BLE/RS485 polling,
  more WiFi traffic, slightly higher load on the inverter/BMS). The component
  always requests fast data every 5 s; the interval is no longer user-configurable.
- The server's own global fast-data poller also runs every 5 minutes for all
  online devices — it overlaps harmlessly.
- There is **no authentication** involved: the server pushes live data to any
  WebSocket client and accepts `requestDataUpdate` without login. Do not
  expose the server publicly without protection.
- Data is received as it arrives; entities that have not received a value yet
  show as "unknown".
- Removing a BMS slot does not remove its already-created cell sensors;
  reload the integration if you physically remove a BMS.

## Development / layout

```
custom_components/solarproject/
├── __init__.py        # entry-point setup/unload, device registry
├── binary_sensor.py   # online/offline, Lux cloud, BMS connection states
├── config_flow.py     # server URL + device ID validation, options flow
├── const.py           # field metadata (units, device classes, scaling)
├── coordinator.py     # WebSocket client, reconnect, fast-data loop, parser
├── manifest.json
├── sensor.py          # all numeric/text sensor entities
└── translations/      # en, vi UI strings
```

### Scaling of raw values (matches the web UI)

| Field | Raw unit | Sensor unit |
|---|---|---|
| BMS vbat, cur, t0-t5 | 0.1 V / 0.1 A / 0.1 °C | V / A / °C (÷10) |
| BMS cap | mAh | Ah (÷1000) |
| BMS vcells | mV | V (÷1000) |
| Inverter fields | as-is | as-is |