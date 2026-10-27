# SolarBox for Home Assistant

Connect a SolarBox dongle to Home Assistant for inverter and BMS monitoring.
Supported local firmware also provides inverter controls over WebSocket.

## Install with HACS

1. Open **HACS** in Home Assistant, then **⋮ → Custom repositories**.
2. Add `https://github.com/xuantrandev/solarbox_ha` with type **Integration**.
3. Find **solarbox.uk devices** in HACS and download it.
4. Restart Home Assistant.
5. Open **Settings → Devices & services → Add integration** and select
   **solarbox.uk devices**.
6. Enter your dongle's Device ID (`dg-xxxxxx`) and Server URL:
   - Local monitoring and supported inverter controls: `http://<dongle-ip>:8001`.
   - Cloud monitoring: `https://ivbms.solarbox.uk` or your existing server URL.

Add one integration entry per dongle. Reserve the dongle's LAN IP when using a
local connection.

For an existing manual installation, install through HACS and restart Home
Assistant. Keep your existing integration entries. Entity IDs now use the
configured sensor prefix (or the device ID when empty); see the integration
documentation for migration behavior and dashboard/automation reference updates.

Version `1.1.3` also supports Home Assistant 2026.10's device-aware ID generation.
Version `1.1.2` added the original prefix naming fix. Earlier code also used
version `1.1.1`, so that version alone does not confirm the fix is installed. After
updating the integration files, restart Home Assistant to load the new Python
code. In the integration's Configure dialog, set **Sensor prefix** to `dg` to
generate IDs such as `sensor.dg_bms1_cell_voltage_1`; changing only the device
name does not set this prefix.

## Manual installation

Copy `custom_components/solarproject` into your Home Assistant
`config/custom_components/` directory, restart Home Assistant, then follow the
configuration steps above.

See the [integration documentation](custom_components/solarproject/README.md)
for controls, connection behavior, and development verification.

## Publishing and updates

HACS requires this GitHub repository to be public. Add a repository description,
enable issues, and set topics such as `hacs`, `home-assistant`, and `solarbox` in
the GitHub repository settings.

Push this repository's contents to `xuantrandev/solarbox_ha`; use that repository
URL in HACS, rather than the parent `solarproject` workspace or a subdirectory URL.
The validation workflow runs HACS validation and Home Assistant hassfest on
pushes and pull requests, and can also be run manually.

HACS can install from the default branch without a release. For versioned
updates, update `custom_components/solarproject/manifest.json` and publish a
GitHub release with a matching version tag (for example, `v1.1.3` for manifest
version `1.1.3`). No custom ZIP asset is needed. Being installable as a custom
repository does not automatically add this integration to HACS's default catalog.

## Select inverter or MQ sensors

Version `1.2.0` adds **Sensor profile** to setup and **Configure** for each dongle:

- **Inverter + BMS (home_senble.yaml)** keeps the existing inverter/BMS entities
  and supported local inverter controls. Existing entries use this profile.
- **MQ + BMS (home_mq2ha.yaml)** uses `home_mqble.yaml` firmware to expose the
  MQ controller and BMS sensors matching the native `home_mq2ha.yaml` firmware.
  This includes cell resistance, voltage summaries, balancing, capacity,
  error/runtime/version text, and dongle temperature/uptime. Three BMS slots
  are supported; unavailable backend readings remain unknown.

For MQ local access, install `solardongle/home_mqble.yaml` on the dongle, select
**MQ + BMS**, and enter `http://<dongle-ip>:8001` with its `dg-xxxxxx` Device ID.
`home_mq2ha.yaml` remains the separate native ESPHome firmware; the integration
connects to the WebSocket firmware rather than reading a YAML file at runtime.
MQ local delivery continues while cloud fast-data streaming is off or the MQTT
broker is unavailable. Cloud connections can use MQ controller telemetry too. The MQ profile uses
native BMS/dongle readings for reference parity and requires the local endpoint
for those readings.

Changing profiles reloads the integration. Inactive profile entities are disabled
and retained with their history; switching back restores integration-disabled
entities while preserving user-disabled choices. Shared BMS identities remain
unchanged. The MQ profile provides monitoring, without inverter controls or BMS
write controls.

## MQ without BMS

Version `1.2.1` adds **MQ only (home_mq.yaml)** to setup and Configure.
For `solardongle/home_mq.yaml` firmware, select this profile and enter
`http://<dongle-ip>:8001` with the dongle's `dg-xxxxxx` Device ID.
It exposes MQ controller readings, dongle temperature/uptime, Wi-Fi signal,
device information and online status without BMS entities or inverter controls.
MQ battery voltage/current/power remain available from the controller without a BMS.
Local power readings retain fractional watts; cloud telemetry uses the existing
MQ fallback, while native dongle temperature/uptime require the local endpoint.

Existing profiles and their defaults are preserved. Switching to MQ only disables
existing BMS entities and retains their history. Switching back restores entities
disabled by the integration and preserves user-disabled choices. Shared MQ and
dongle entities keep their identities across MQ profile changes.
