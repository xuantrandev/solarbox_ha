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
Assistant. Keep your existing integration entries and sensor prefixes to retain
entity IDs and history.

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
GitHub release with a matching version tag (for example, `v1.1.1` for manifest
version `1.1.1`). No custom ZIP asset is needed. Being installable as a custom
repository does not automatically add this integration to HACS's default catalog.
