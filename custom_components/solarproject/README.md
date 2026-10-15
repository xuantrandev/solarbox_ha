# SolarProject Home Assistant integration

Connect Home Assistant directly to a `home_senble` dongle or use the existing
`solardongleweb` monitoring endpoint. Updated local firmware exposes 18 inverter
settings over WebSocket: 14 numbers, three selects and one switch. Existing
inverter/BMS sensors and scaling are preserved.

Entity names match `solardongle/home_senjkha.yaml` wherever a corresponding
entity exists, including inherited BMS definitions. HA uses these complete names
without prepending the dongle/device name (for example, `Ivt PV Today Lux`,
`bms1 total voltage`, and `Ivt Work Mode`). Entity IDs use the configured sensor
prefix followed by the entity name, normalized by Home Assistant. For example,
device `dg-9d8740` with prefix `dg` creates `sensor.dg_bms1_cell_voltage_2`.
The prefix applies to sensors, binary sensors, and inverter controls. An empty
prefix uses the device ID, producing `sensor.dg_9d8740_bms1_cell_voltage_2`.
Friendly names remain unchanged.

On setup or after a prefix change, recognizable generated IDs are migrated in
place, including older IDs with the device name and IDs without a prefix.
Existing registry records, custom entity IDs, custom names and entity settings
are preserved; prefix-based unique IDs are updated in place. Ambiguous IDs are
left unchanged. Occupied migration targets are skipped and logged. New entities
use Home Assistant's usual numeric suffix when their requested entity ID is busy.
After migration, update dashboard and automation references that use renamed
entity IDs. Renaming registry records does not rewrite those references or
guarantee that recorder history under an old entity ID is moved.

## Configure

For HACS installation, follow the [repository installation guide](../../README.md#install-with-hacs).
For manual installation:

Copy `custom_components/solarproject` into HA's `config/custom_components/`,
restart HA, and add **solarbox.uk devices** under Settings → Devices & Services.
Enter the existing Device ID (`dg-xxxxxx`) and Server URL:

- Local monitoring and inverter controls: `http://<dongle-ip>:8001`.
- Cloud monitoring: the existing server URL, such as `https://ivbms.solarbox.uk`.

HA connects to `/ws/<deviceId>`. Reserve the dongle's LAN IP. Add one integration
entry per dongle and choose distinct prefixes for different dongles. Selection
is manual, with no automatic cloud fallback. Local WS has no
authentication and supports two clients; use it on a trusted LAN.

Both the updated firmware and updated integration are needed for controls.
Older local firmware and cloud endpoints without the versioned settings catalog
continue to provide monitoring. This interface does not implement cloud writes,
BMS configuration, Wi-Fi settings, Bluetooth configuration, restart or updates.

## Inverter controls

The active `ctl_*` definitions from `solardongle/home_senjkha.yaml` are shared
through `platform/sve_home_controls.yaml`. Their names, icons, units, limits,
steps and select options determine the local catalog. Commented controls are
excluded. Firmware owns all register addresses, select mappings and conversion
between displayed units and raw register values.

Controls include work mode, battery type, capacity mode, grid charge, battery
capacity, power/current limits, SOC limits and charge/discharge voltages.
`Ivt EOD Voltage` deliberately retains the reference name and its existing SOC
register with `%` units. New unique IDs use the existing prefix plus the stable
`ctl_*` key, independent of the display name.

HA services (`number.set_value`, `select.select_option`, `switch.turn_on/off`)
wait up to ten seconds for firmware acceptance. Acceptance means validation
passed and the command entered the inverter write queue. It does not confirm a
physical setting change. Displayed values update only from inverter readback,
never optimistically from a request or acceptance result. Configuration refresh
runs on local connection, every 60 seconds, and after an acknowledged write.
Readback can differ from the requested value if the inverter rejects or adjusts
it, or another controller changes it.

Rejected, disconnected and timed-out commands raise an HA service error. The
dongle limits outstanding local commands across both clients to eight and
rejects excess work as busy. Closing a session drops its unexecuted local
commands. Neither endpoint retries or replays writes after reconnect. A timeout
can occur after acceptance if the result is lost; check readback before retrying.

Controls are unavailable until their catalog and fresh readback arrive, and
while the inverter or WS is disconnected. Sensor data and settings delivery
remain independent of MQTT fast-data mode; local demand creates no additional
MQTT control entities or telemetry. A broker outage cannot trigger MQTT's reboot
timeout in `home_senble`. Existing cloud delivery and commands remain supported.

## Verification

Run from the `solarbox_ha` root. Tests use simulated endpoints and temporary HA
configuration; they do not restart an existing instance or operate hardware.

```bash
docker run --rm --entrypoint python -v "$PWD:/work:ro" \
  ghcr.io/home-assistant/home-assistant:stable /work/ha_test/test_local_ws.py
docker run --rm --entrypoint python -v "$PWD:/work:ro" \
  ghcr.io/home-assistant/home-assistant:stable /work/ha_test/test_local_ws_runtime.py
docker run --rm --entrypoint python -v "$PWD:/work:ro" \
  ghcr.io/home-assistant/home-assistant:stable /work/ha_test/test_inverter_settings.py
docker run --rm --entrypoint python -v "$PWD:/work:ro" \
  ghcr.io/home-assistant/home-assistant:stable /work/ha_test/test_inverter_settings_runtime.py
docker run --rm --entrypoint python -v "$PWD:/work:ro" \
  ghcr.io/home-assistant/home-assistant:stable /work/ha_test/test_entity_naming_runtime.py
```

The settings fixture mirrors the firmware-generated catalog; the firmware host
test checks it against actual code generation when both repositories are present.
Tests cover all three control platforms, actual HA service calls, readback-only
state, errors/timeouts, concurrent request correlation, fresh-state requirements,
reloads and reconnects without replay. Naming tests cover configured/default
prefixes, registry migration, custom IDs/names, collisions and prefix changes.
Legacy tests cover scaling and dynamic
BMS cells. Real TCP/BLE readback, ESP32 heartbeat/Wi-Fi recovery, simultaneous
clients and broker-outage operation require hardware checks. Flashing and
production deployment are separate steps.
