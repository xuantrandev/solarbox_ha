"""Run with Home Assistant installed, using the documented isolated Docker command."""
import asyncio
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from custom_components.solarproject import sensor, binary_sensor, config_flow, settings
from custom_components.solarproject.const import (
    BMS_SLOTS, CONF_SENSOR_PROFILE, DEFAULT_SENSOR_PROFILE,
    INVERTER_FIELDS, MQ_FIELDS, PROFILE_MQ,
    PROFILE_INVERTER, home_native_keys, is_mq_profile,
)
from custom_components.solarproject.coordinator import SolarProjectCoordinator
from custom_components.solarproject.entity import (
    async_apply_sensor_profile,
)


class SensorProfiles(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.hass = HomeAssistant(self.tmp.name)
        self.entry = SimpleNamespace(data={"device_id": "dg-aabbcc", "server": "http://dongle:8001"}, entry_id="test")
        self.coordinator = SolarProjectCoordinator(self.hass, self.entry.data)

    async def entities(self, profile=None):
        if profile:
            self.entry.data[CONF_SENSOR_PROFILE] = profile
        else:
            self.entry.data.pop(CONF_SENSOR_PROFILE, None)
        entities = []
        with patch.object(sensor, "get_coordinator", return_value=self.coordinator):
            await sensor.async_setup_entry(self.hass, self.entry, entities.extend)
        binary = []
        with patch.object(binary_sensor, "get_coordinator", return_value=self.coordinator):
            await binary_sensor.async_setup_entry(self.hass, self.entry, binary.extend)
        return {e._key: e for e in entities}, {e._key: e for e in binary}

    async def test_existing_entry_defaults_and_profile_entity_sets(self):
        entities, binary = await self.entities()
        self.assertFalse(is_mq_profile(self.entry))
        self.assertTrue(set(INVERTER_FIELDS) <= entities.keys())
        self.assertFalse(set(MQ_FIELDS) & entities.keys())
        self.assertIn("lux_server_state", binary)
        mq, mq_binary = await self.entities(PROFILE_MQ)
        self.assertTrue(set(MQ_FIELDS) <= mq.keys())
        self.assertFalse(set(INVERTER_FIELDS) & mq.keys())
        self.assertNotIn("lux_server_state", mq_binary)
        self.assertIn("bms3_native_balancing", mq_binary)
        self.assertEqual(mq["wifi_signal"].name, "Dongle WiFi Signal Strength")
        self.assertEqual(entities["bms1_soc"].unique_id, mq["bms1_soc"].unique_id)
        self.assertNotEqual(entities["pdc1"].unique_id, mq["mq_pdc1"].unique_id)
        with patch.object(settings, "get_coordinator") as get:
            settings.setup_controls(self.hass, self.entry, lambda entities: self.fail("MQ controls"), "number", object)
            get.assert_not_called()

    async def test_mq_units_signs_text_and_unknown_values(self):
        entities, _ = await self.entities(PROFILE_MQ)
        self.assertIsNone(entities["mq_bcur"].native_value)
        self.coordinator._process_message({"type": "ivtdata", "datatype": "invtlive", "data": {
            "vdc1": 80, "idc1": 10, "pdc1": 800, "vbat": 50, "bcur": -15,
            "pbat": -750, "pvtd": 1234, "status_text": "Đang Sạc", "efficiency": 93.75,
        }})
        self.coordinator._process_message({"type": "ivtdata", "datatype": "invtstatis", "data": {"pvall": 98.765, "dctemp": 32}})
        for key, expected in {"mq_idc1": 10, "mq_bcur": 15, "mq_pbat": 750, "mq_pvtd": 1.234, "mq_pvall": 98.765, "mq_dctemp": 32}.items():
            self.assertAlmostEqual(entities[key].native_value, expected)
        self.assertEqual(entities["mq_status_text"].native_value, "Đang Sạc")
        self.assertEqual(entities["mq_pvtd"].native_unit_of_measurement, "kWh")
        self.assertEqual(entities["mq_pvtd"].state_class, "total_increasing")
        self.assertIsNone(entities["bms1_native_design_capacity"].native_value)
        self.coordinator._process_message({"type": "homeSensorData", "deviceId": "dg-aabbcc", "data": {
            "mq_native_pv_power": 800.24, "mq_native_battery_power": 750.8,
        }})
        self.assertEqual(entities["mq_pdc1"].native_value, 800.24)
        self.assertEqual(entities["mq_pbat"].native_value, 750.8)

    async def test_native_values_cells_and_foreign_device_rejection(self):
        entities, binary = await self.entities(PROFILE_MQ)
        payload = {"type": "homeSensorData", "deviceId": "dg-other", "data": {
            "bms1_native_design_capacity": 280.5, "bms1_native_cell_resistance_1": 0.003,
            "bms1_native_software_version": "v1", "bms1_native_balancing": True,
            "bms1_native_average_cell_voltage": 3.2876,
            "dongle_uptime": 900, "pdc1": 123456,
            "bms1_native_total_voltage": 52.55, "bms1_native_capacity_remaining": 160.5,
            "bms1_native_temperature_sensor_1": 25.5, "bms1_native_mosfet_temperature": 38.2,
            "bms1_native_cell_voltage_1": 3.279, "bms1_native_cell_voltage_2": 3.3,
            "bms1_native_charging": True, "bms1_native_discharging": False,
            "bms1_native_mac": "11:22:33:44:55:66",
        }}
        self.coordinator._process_message(payload)
        self.assertIsNone(entities["bms1_native_design_capacity"].native_value)
        payload["deviceId"] = "dg-aabbcc"
        self.coordinator._process_message(payload)
        self.assertEqual(entities["bms1_native_design_capacity"].native_value, 280.5)
        self.assertEqual(entities["bms1_native_cell_resistance_1"].native_value, 0.003)
        self.assertEqual(entities["bms1_native_software_version"].native_value, "v1")
        self.assertTrue(binary["bms1_native_balancing"].is_on)
        self.assertEqual(entities["bms1_native_average_cell_voltage"].native_value, 3.2876)
        self.assertNotIn("pdc1", self.coordinator.data)
        # Exercise the actual dynamic-cell callback and scaling.
        self.coordinator._process_message({"type": "bmsData", "bmsType": "bms1", "data": {"vbat": 525, "vcells": [3279, 3300]}})
        await asyncio.sleep(0)
        self.assertEqual(entities["bms1_vbat"].native_value, 52.55)
        self.assertEqual(entities["bms1_cap"].native_value, 160.5)
        self.assertEqual(entities["bms1_t0"].native_value, 25.5)
        self.assertEqual(entities["bms1_t4"].native_value, 38.2)
        self.assertEqual(entities["bms1_mac"].native_value, "11:22:33:44:55:66")
        self.assertTrue(binary["bms1_chg"].is_on)
        self.assertFalse(binary["bms1_dischg"].is_on)
        cell = sensor.BmsCellSensor(self.coordinator, "bms1", 1, self.entry)
        self.assertEqual(cell.native_value, 3.279)
        payload["data"] = {"bms1_native_total_voltage": None}
        self.coordinator._process_message(payload)
        self.assertIsNone(entities["bms1_vbat"].native_value)

    async def test_reference_sensor_name_parity(self):
        reference = Path("/firmware/release_mqjkha.yaml")
        if not reference.exists():
            self.skipTest("Mount solardongle at /firmware for reference parity")
        # Sensor and text_sensor sections end at binary_sensor/switch controls.
        text = reference.read_text()
        text = text[text.index("mq_uart:"):text.index("switch:")]
        expected = set(re.findall(r'name: "([^"\n]+)"', text))
        # MAC address template definitions are in this span; include them too.
        expected = {name.replace("${bms1name}", "bms1").replace("${bms2name}", "bms2") for name in expected}
        # MPPT ID is commented out in the reference.
        expected.discard("MPPT ID")
        entities, binary = await self.entities(PROFILE_MQ)
        names = {entity.name for entity in [*entities.values(), *binary.values()]}
        names.update(f"bms{slot} cell voltage {i}" for slot in BMS_SLOTS for i in range(1, 17))
        self.assertEqual(expected - names, set())

    async def test_native_schema_alignment_and_early_cell_replay(self):
        import yaml
        source = Path("/firmware/platform/mq_home_sensors.yaml")
        if not source.exists():
            self.skipTest("Mount solardongle at /firmware")
        package = yaml.safe_load(source.read_text())
        bindings = package["local_ws"]["home_sensors"]
        self.assertEqual({binding["key"] for binding in bindings}, home_native_keys())
        self.assertEqual(len(bindings), len(home_native_keys()))
        # Native replay may arrive before HA has registered the sensor platform.
        self.coordinator._process_message({"type": "homeSensorData", "deviceId": "dg-aabbcc", "data": {
            "bms1_native_cell_voltage_1": 3.28, "bms1_native_cell_voltage_2": 3.29,
        }})
        created = []
        async def add(slot, indices):
            created.append((slot, indices))
        self.coordinator.register_cell_adder(add)
        await asyncio.sleep(0)
        self.assertEqual(created, [("bms1", [1, 2])])

    async def test_profile_registry_switch_and_user_disabled_preservation(self):
        def registered(key, name, disabled=None):
            return SimpleNamespace(platform="solarproject", domain="sensor", unique_id=f"solarproject_dg-aabbcc_{key}", original_name=name,
                                   entity_id=f"sensor.test_{key}", disabled_by=disabled)
        inv = registered("pdc1", "Ivt PV1 Power")
        mq = registered("mq_pdc1", "MQ PV Power", er.RegistryEntryDisabler.INTEGRATION)
        user = registered("mq_vdc1", "MQ PV Voltage", er.RegistryEntryDisabler.USER)
        common = registered("bms1_soc", "bms1 state of charge")
        registry = MagicMock()
        self.entry.data[CONF_SENSOR_PROFILE] = PROFILE_MQ
        with patch("custom_components.solarproject.entity.entity_registry.async_get", return_value=registry), patch(
            "custom_components.solarproject.entity.entity_registry.async_entries_for_config_entry", return_value=[inv, mq, user, common]
        ):
            async_apply_sensor_profile(self.hass, self.entry, self.coordinator)
        calls = registry.async_update_entity.call_args_list
        self.assertEqual(len(calls), 2)
        registry.async_update_entity.assert_any_call(inv.entity_id, disabled_by=er.RegistryEntryDisabler.INTEGRATION)
        registry.async_update_entity.assert_any_call(mq.entity_id, disabled_by=None)
        inv.disabled_by = er.RegistryEntryDisabler.INTEGRATION
        mq.disabled_by = None
        self.entry.data[CONF_SENSOR_PROFILE] = PROFILE_INVERTER
        registry.reset_mock()
        with patch("custom_components.solarproject.entity.entity_registry.async_get", return_value=registry), patch(
            "custom_components.solarproject.entity.entity_registry.async_entries_for_config_entry", return_value=[inv, mq, user, common]
        ):
            async_apply_sensor_profile(self.hass, self.entry, self.coordinator)
        registry.async_update_entity.assert_any_call(inv.entity_id, disabled_by=None)
        registry.async_update_entity.assert_any_call(mq.entity_id, disabled_by=er.RegistryEntryDisabler.INTEGRATION)
        self.assertEqual(registry.async_update_entity.call_count, 2)

    async def test_setup_and_options_profile_persistence(self):
        flow = config_flow.SolarProjectConfigFlow()
        flow.hass = self.hass
        with patch.object(flow, "async_set_unique_id", new_callable=AsyncMock), patch.object(flow, "_abort_if_unique_id_configured"), patch.object(
            config_flow, "_validate_connection", new_callable=AsyncMock
        ):
            result = await flow.async_step_user({"server": "http://dongle:8001", "device_id": "dg-aabbcc", CONF_SENSOR_PROFILE: PROFILE_MQ})
        self.assertEqual(result["data"][CONF_SENSOR_PROFILE], PROFILE_MQ)
        options = config_flow.SolarProjectOptionsFlow()
        options.hass = MagicMock()
        options.hass.config_entries.async_reload = AsyncMock()
        with patch.object(config_flow.SolarProjectOptionsFlow, "config_entry", new_callable=PropertyMock, return_value=self.entry):
            form = await options.async_step_init()
            validated = form["data_schema"]({"server": "http://dongle:8001"})
            self.assertEqual(validated[CONF_SENSOR_PROFILE], DEFAULT_SENSOR_PROFILE)
            await options.async_step_init({"server": "http://dongle:8001", CONF_SENSOR_PROFILE: PROFILE_MQ})
        data = options.hass.config_entries.async_update_entry.call_args.kwargs["data"]
        self.assertEqual(data[CONF_SENSOR_PROFILE], PROFILE_MQ)
        options.hass.config_entries.async_reload.assert_awaited_once_with("test")


if __name__ == "__main__":
    unittest.main()
