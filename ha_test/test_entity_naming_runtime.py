"""Exercise prefix naming and registry migration in isolated, real HA instances."""

import asyncio
import json
from pathlib import Path
import sys
import tempfile
from types import MappingProxyType
import unittest
from unittest.mock import AsyncMock, patch

from aiohttp import ClientSession, web
from homeassistant import loader
from homeassistant.components.network import async_get_network
from homeassistant.config_entries import ConfigEntries, ConfigEntry, ConfigEntryDisabler
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry, device_registry, entity_registry, issue_registry

# Keep the custom_components namespace valid across temporary HA instances.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ID = "dg-9d8740"
DOMAIN = "solarproject"
CATALOG = json.loads(Path(__file__).with_name("inverter_settings_catalog.json").read_text())
VALUES = {
    spec["key"]: (spec["min"] if spec["platform"] == "number" else
                  spec["options"][0] if spec["platform"] == "select" else False)
    for spec in CATALOG
}


class EntityNamingTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async def stream(request):
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            for payload in [
                {"type": "deviceStatus", "deviceId": ID, "status": "online"},
                {"type": "ivtdata", "data": {"vbat": 52.5, "pdc1": 120}},
                {"type": "bmsData", "bmsType": "bms1", "data": {"vcells": [3279, 3280]}},
                {"type": "inverterSettingsCatalog", "deviceId": ID, "version": 1, "settings": CATALOG},
                {"type": "inverterSettingsState", "deviceId": ID, "version": 1,
                 "available": True, "values": VALUES},
            ]:
                await ws.send_json(payload)
            async for _ in ws:
                pass
            return ws

        app = web.Application()
        app.router.add_get("/ws/" + ID, stream)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]
        self.directory = tempfile.TemporaryDirectory(prefix="solarproject-naming-runtime-")
        root = Path(self.directory.name)
        (root / "custom_components").mkdir()
        (root / "custom_components/solarproject").symlink_to(
            Path(__file__).resolve().parents[1] / "custom_components/solarproject",
            target_is_directory=True,
        )
        self.hass = HomeAssistant(self.directory.name)
        self.hass.config.skip_pip = True
        loader.async_setup(self.hass)
        self.hass.config_entries = ConfigEntries(self.hass, {})
        await self.hass.config_entries.async_initialize()
        if setup_devices := getattr(device_registry, "async_setup", None):
            setup_devices(self.hass)
        await asyncio.gather(*(registry.async_load(self.hass) for registry in
                               (area_registry, device_registry, entity_registry, issue_registry)))
        await async_get_network(self.hass)
        self.registry = entity_registry.async_get(self.hass)
        # Use a per-test HTTP session so HA's global Zeroconf singleton does not
        # span the separate event loops used by IsolatedAsyncioTestCase.
        self.session = ClientSession()
        self.session_patch = patch(
            "custom_components.solarproject.coordinator.async_get_clientsession",
            return_value=self.session,
        )
        self.session_patch.start()

    async def asyncTearDown(self):
        for entry_id in list(self.hass.data.get(DOMAIN, {})):
            await self.hass.config_entries.async_unload(entry_id)
        await self.session.close()
        self.session_patch.stop()
        await self.hass.async_stop()
        await self.runner.cleanup()
        self.directory.cleanup()

    async def entry(self, prefix="dg", device_id=ID):
        data = {"server": f"http://127.0.0.1:{self.port}", "device_id": device_id,
                "fast_data_interval": 0, "name": "Roof Dongle"}
        if prefix is not None:
            data["sensor_prefix"] = prefix
        entry = ConfigEntry(
            version=1, minor_version=1, domain=DOMAIN, title=device_id, data=data,
            options={}, source="user", unique_id=device_id,
            disabled_by=ConfigEntryDisabler.USER if device_id != ID else None,
            discovery_keys=MappingProxyType({}), subentries_data=[],
        )
        # Register the config entry, then seed legacy records before its first setup.
        with patch.object(self.hass.config_entries, "async_setup", AsyncMock(return_value=True)):
            await self.hass.config_entries.async_add(entry)
        return entry

    def seed(self, entry, platform, key, object_id, name, prefix=ID, **kwargs):
        return self.registry.async_get_or_create(
            platform, DOMAIN, f"{DOMAIN}_{prefix}_{key}",
            config_entry=entry, suggested_object_id=object_id, original_name=name, **kwargs,
        )

    async def setup(self, entry):
        self.assertTrue(await self.hass.config_entries.async_setup(entry.entry_id))
        await self.ready()

    async def ready(self):
        async with asyncio.timeout(10):
            while (not any(s.entity_id.endswith("bms1_cell_voltage_2") for s in self.hass.states.async_all())
                   or len(self.hass.states.async_all("number")) != 14):
                await asyncio.sleep(.02)
        await self.hass.async_block_till_done()

    def registered_id(self, platform, key, prefix="dg"):
        return self.registry.async_get_entity_id(platform, DOMAIN, f"{DOMAIN}_{prefix}_{key}")

    async def test_configured_prefix_all_platforms_and_reload(self):
        entry = await self.entry()
        await self.setup(entry)
        for platform, key, object_id in [
            ("sensor", "bms1_vcells_2", "dg_bms1_cell_voltage_2"),
            ("sensor", "vbat", "dg_ivt_battery_voltage"),
            ("binary_sensor", "bms1_connected", "dg_bms1_online_status"),
            ("number", "ctl_max_charge_current", "dg_ivt_max_charge_current"),
            ("select", "ctl_work_mode", "dg_ivt_work_mode"),
            ("switch", "ctl_grid_charge", "dg_ivt_grid_charge"),
        ]:
            self.assertEqual(self.registered_id(platform, key), f"{platform}.{object_id}")
        cell = self.hass.states.get("sensor.dg_bms1_cell_voltage_2")
        self.assertEqual(float(cell.state), 3.28)
        self.assertTrue(cell.attributes["friendly_name"].endswith("bms1 cell voltage 2"))
        count = len(self.registry.entities)
        await self.hass.config_entries.async_reload(entry.entry_id)
        await self.ready()
        self.assertEqual(len(self.registry.entities), count)
        self.assertEqual(self.registered_id("sensor", "bms1_vcells_2"), cell.entity_id)

    async def test_empty_prefix_uses_device_id(self):
        entry = await self.entry(prefix=None)
        await self.setup(entry)
        self.assertEqual(self.registered_id("sensor", "bms1_vcells_2", ID),
                         "sensor.dg_9d8740_bms1_cell_voltage_2")
        await self.hass.config_entries.async_unload(entry.entry_id)
        self.hass.config_entries.async_update_entry(entry, data={**entry.data, "sensor_prefix": "   "})
        await self.setup(entry)
        self.assertEqual(self.registered_id("sensor", "bms1_vcells_2", ID),
                         "sensor.dg_9d8740_bms1_cell_voltage_2")

    async def test_existing_configured_prefix_removes_device_id_from_cell_id(self):
        entry = await self.entry(prefix="dg")
        legacy = self.seed(
            entry, "sensor", "bms1_vcells_1", "dg_9d8740_bms1_cell_voltage_1",
            "bms1 cell voltage 1", prefix="dg", has_entity_name=True,
        )
        await self.setup(entry)
        target = "sensor.dg_bms1_cell_voltage_1"
        self.assertEqual(self.registered_id("sensor", "bms1_vcells_1"), target)
        self.assertEqual(self.registry.async_get(target).id, legacy.id)
        self.assertIsNone(self.registry.async_get(legacy.entity_id))
        self.assertEqual(float(self.hass.states.get(target).state), 3.279)
        count = len(self.registry.entities)
        await self.hass.config_entries.async_reload(entry.entry_id)
        await self.ready()
        self.assertEqual(self.registered_id("sensor", "bms1_vcells_1"), target)
        self.assertEqual(len(self.registry.entities), count)

    async def test_prefix_is_slugified(self):
        entry = await self.entry(prefix="  My DG!  ")
        await self.setup(entry)
        self.assertEqual(self.registered_id("sensor", "bms1_vcells_2", "My DG!"),
                         "sensor.my_dg_bms1_cell_voltage_2")

    async def test_migrate_legacy_ids_then_change_prefix(self):
        entry = await self.entry()
        legacy = [
            self.seed(entry, "sensor", "bms1_vcells_2", "dg_9d8740_bms1_cell_voltage_2", "bms1 cell voltage 2"),
            self.seed(entry, "sensor", "vbat", "ivt_battery_voltage", "Ivt Battery Voltage"),
            self.seed(entry, "binary_sensor", "bms1_connected", "roof_dongle_bms1_online_status", "bms1 online status"),
            self.seed(entry, "number", "ctl_max_charge_current", "dg_9d8740_ivt_max_charge_current", "Ivt Max Charge Current"),
            self.seed(entry, "select", "ctl_work_mode", "ivt_work_mode", "Ivt Work Mode"),
            self.seed(entry, "switch", "ctl_grid_charge", "dg_9d8740_ivt_grid_charge", "Ivt Grid Charge"),
        ]
        custom = self.seed(entry, "number", "ctl_battery_ah", "my_battery_capacity", "Ivt Battery Capacity")
        self.registry.async_update_entity(custom.entity_id, name="My battery capacity", icon="mdi:heart", aliases={"Capacity"})
        disabled = self.seed(entry, "sensor", "vdc2", "ivt_pv2_voltage", "Ivt PV2 Voltage",
                             disabled_by=entity_registry.RegistryEntryDisabler.USER)
        await self.setup(entry)
        for old, target in zip(legacy, [
            "sensor.dg_bms1_cell_voltage_2", "sensor.dg_ivt_battery_voltage",
            "binary_sensor.dg_bms1_online_status", "number.dg_ivt_max_charge_current",
            "select.dg_ivt_work_mode", "switch.dg_ivt_grid_charge",
        ]):
            migrated = self.registry.async_get(target)
            self.assertIsNotNone(migrated)
            self.assertEqual(migrated.id, old.id)
            self.assertTrue(migrated.unique_id.startswith("solarproject_dg_"))
        self.assertEqual(self.registry.async_get("sensor.dg_ivt_pv2_voltage").id, disabled.id)
        self.assertEqual(self.registry.async_get("sensor.dg_ivt_pv2_voltage").disabled_by,
                         entity_registry.RegistryEntryDisabler.USER)
        count = len(self.registry.entities)
        await self.hass.config_entries.async_unload(entry.entry_id)
        self.hass.config_entries.async_update_entry(entry, data={**entry.data, "sensor_prefix": "new"})
        await self.setup(entry)
        self.assertEqual(self.registered_id("sensor", "bms1_vcells_2", "new"),
                         "sensor.new_bms1_cell_voltage_2")
        self.assertEqual(self.registry.async_get("sensor.new_bms1_cell_voltage_2").id, legacy[0].id)
        self.assertEqual(self.registered_id("number", "ctl_battery_ah", "new"), custom.entity_id)
        saved = self.registry.async_get(custom.entity_id)
        self.assertEqual((saved.id, saved.name, saved.icon, saved.aliases),
                         (custom.id, "My battery capacity", "mdi:heart", {"Capacity"}))
        self.assertEqual(len(self.registry.entities), count)
        await self.hass.config_entries.async_reload(entry.entry_id)
        await self.ready()
        self.assertEqual(len(self.registry.entities), count)

    async def test_collisions_other_entries_and_ambiguous_ids(self):
        entry = await self.entry()
        other = await self.entry(prefix="other", device_id="dg-aabbcc")
        untouched = self.seed(other, "sensor", "vbat", "other_ivt_battery_voltage", "Ivt Battery Voltage", prefix="other")
        # Occupied desired entity ID: retain the legacy record and its ID.
        occupied = self.registry.async_get_or_create("sensor", "test", "occupied", suggested_object_id="dg_bms1_cell_voltage_2")
        legacy = self.seed(entry, "sensor", "bms1_vcells_2", "dg_9d8740_bms1_cell_voltage_2", "bms1 cell voltage 2")
        # A new entity uses HA's usual numeric suffix when its requested ID is busy.
        self.registry.async_get_or_create("sensor", "test", "new-collision", suggested_object_id="dg_ivt_pv1_power")
        # A unique-ID collision with another entry must not take over that record.
        conflicting = self.seed(other, "sensor", "vdc1", "other_pv1_voltage", "Ivt PV1 Voltage", prefix="dg")
        retained = self.seed(entry, "sensor", "vdc1", "ivt_pv1_voltage", "Ivt PV1 Voltage")
        ambiguous = self.seed(entry, "sensor", "soc", "my_custom_state_of_charge", "Ivt Battery SOC")
        numbered = self.seed(entry, "sensor", "vgr", "ivt_grid_voltage_2", "Ivt Grid Voltage")
        self.hass.states.async_reserve("sensor.dg_wifi_signal")
        reserved = self.seed(entry, "sensor", "wifi_signal", "wifi_signal", "Wifi Signal")
        with self.assertLogs("custom_components.solarproject.entity", level="WARNING") as logs:
            await self.setup(entry)
        self.assertTrue(any("is occupied" in line for line in logs.output))
        self.assertTrue(any("unique ID migration" in line for line in logs.output))
        self.assertEqual(self.registry.async_get(legacy.entity_id).id, legacy.id)
        self.assertEqual(self.registry.async_get(occupied.entity_id).id, occupied.id)
        self.assertEqual(self.registry.async_get(untouched.entity_id), untouched)
        self.assertEqual(self.registry.async_get(conflicting.entity_id), conflicting)
        self.assertEqual(self.registry.async_get(retained.entity_id).unique_id, retained.unique_id)
        self.assertIsNotNone(self.hass.states.get(retained.entity_id))
        self.assertEqual(self.registered_id("sensor", "pdc1"), "sensor.dg_ivt_pv1_power_2")
        self.assertEqual(self.registered_id("sensor", "soc"), ambiguous.entity_id)
        self.assertEqual(self.registered_id("sensor", "vgr"), numbered.entity_id)
        self.assertEqual(self.registered_id("sensor", "wifi_signal"), reserved.entity_id)
        records = entity_registry.async_entries_for_config_entry(self.registry, entry.entry_id)
        self.assertEqual(sum(e.unique_id.endswith("_vdc1") for e in records), 1)


if __name__ == "__main__":
    unittest.main()
