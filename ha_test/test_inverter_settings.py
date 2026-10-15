"""Local settings coordinator/platform tests against a simulated firmware endpoint."""
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from aiohttp import ClientSession, web
from homeassistant.exceptions import HomeAssistantError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from custom_components.solarproject import coordinator as coordinator_module
from custom_components.solarproject import number, select, switch
from custom_components.solarproject.const import DOMAIN

ID = 'dg-aabbcc'
CATALOG = json.loads(Path(__file__).with_name('inverter_settings_catalog.json').read_text())
VALUES = {spec['key']: (spec['min'] if spec['platform'] == 'number' else
                       spec['options'][0] if spec['platform'] == 'select' else False)
          for spec in CATALOG}
VALUES['ctl_max_charge_current'] = 40.0


def catalog():
    return {'type': 'inverterSettingsCatalog', 'deviceId': ID, 'version': 1, 'settings': CATALOG}


def state(**overrides):
    return {'type': 'inverterSettingsState', 'deviceId': ID, 'version': 1, 'available': True,
            'values': dict(VALUES, **overrides)}


class SettingsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.sockets = []
        self.received = asyncio.Queue()
        self.tasks = []
        self.session = ClientSession()

        async def stream(request):
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            self.sockets.append(ws)
            for payload in [{'type': 'deviceStatus', 'deviceId': ID, 'status': 'online'}, catalog(), state()]:
                await ws.send_json(payload)
            async for message in ws:
                await self.received.put(message.json())
            return ws

        app = web.Application()
        app.router.add_get('/ws/' + ID, stream)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, '127.0.0.1', 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]

        def create_task(coro, **kwargs):
            task = asyncio.create_task(coro, **kwargs)
            self.tasks.append(task)
            return task

        self.hass = SimpleNamespace(data={}, async_create_task=create_task)
        self.coord = coordinator_module.SolarProjectCoordinator(self.hass, {
            'server': f'http://127.0.0.1:{port}', 'device_id': ID, 'fast_data_interval': 0})
        self.entry = SimpleNamespace(entry_id='test', data={}, async_on_unload=lambda callback: None)
        self.hass.data[DOMAIN] = {'test': self.coord}
        self.patch_session = patch.object(coordinator_module, 'async_get_clientsession', return_value=self.session)
        self.patch_backoff = patch.object(coordinator_module, 'WS_RECONNECT_MIN', .01)
        self.patch_session.start()
        self.patch_backoff.start()
        await self.coord.async_start()
        await self.ready()

    async def ready(self):
        async with asyncio.timeout(3):
            while not self.coord.settings_available:
                await asyncio.sleep(.01)

    async def asyncTearDown(self):
        await self.coord.async_stop()
        self.patch_session.stop()
        self.patch_backoff.stop()
        await self.session.close()
        await self.runner.cleanup()

    async def result(self, command, accepted=True, **overrides):
        await self.sockets[-1].send_json(dict({
            'type': 'inverterSettingResult', 'deviceId': ID, 'requestId': command['requestId'],
            'accepted': accepted}, **overrides))

    async def test_all_platforms_acceptance_and_readback(self):
        entities = []
        for module in (number, select, switch):
            await module.async_setup_entry(self.hass, self.entry, entities.extend)
        self.assertEqual(len(entities), 24)
        self.assertEqual(len([e for e in entities if isinstance(e, switch.SolarBmsStateSwitch)]), 6)
        self.assertEqual(len([e for e in entities if isinstance(e, number.SolarInverterNumber)]), 14)
        eod = next(e for e in entities if e._key == 'ctl_discharge_end_soc')
        self.assertEqual((eod.name, eod.native_unit_of_measurement), ('Ivt EOD Voltage', '%'))
        for key, value in [('ctl_max_charge_current', 50.1), ('ctl_work_mode', 'Backup'), ('ctl_grid_charge', True)]:
            task = asyncio.create_task(self.coord.async_write_setting(key, value))
            command = await asyncio.wait_for(self.received.get(), 1)
            self.assertEqual((command['type'], command['deviceId'], command['key'], command['value']),
                             ('writeInverterSetting', ID, key, value))
            await self.result(command)
            await task
            self.assertEqual(self.coord.settings_state[key], VALUES[key])
        await self.sockets[-1].send_json(state(ctl_max_charge_current=50.1))
        async with asyncio.timeout(1):
            while self.coord.settings_state['ctl_max_charge_current'] != 50.1:
                await asyncio.sleep(.01)
        self.coord._process_message(catalog())
        self.assertEqual(len(entities), 24)  # Duplicate catalog never duplicates entities.

    async def test_rejection_invalid_values_and_timeout(self):
        for key, value in [('ctl_grid_charge', 1), ('ctl_max_charge_current', True),
                           ('ctl_max_charge_current', float('nan')), ('ctl_max_charge_current', 501),
                           ('ctl_max_charge_current', 50.15), ('ctl_work_mode', 'bad')]:
            with self.subTest(key=key, value=value), self.assertRaises(HomeAssistantError):
                await self.coord.async_write_setting(key, value)
        self.assertTrue(self.received.empty())
        task = asyncio.create_task(self.coord.async_write_setting('ctl_grid_charge', True))
        command = await self.received.get()
        await self.result(command, False, error='busy')
        with self.assertRaisesRegex(HomeAssistantError, 'busy'):
            await task
        with patch.object(coordinator_module, 'SETTING_ACCEPTANCE_TIMEOUT', .03):
            task = asyncio.create_task(self.coord.async_write_setting('ctl_grid_charge', True))
            command = await self.received.get()
            await self.result(command, deviceId='dg-other')
            await self.result(command, requestId='unmatched')
            with self.assertRaisesRegex(HomeAssistantError, 'Timed out'):
                await task
        await self.result(command)  # Late responses are ignored.
        self.assertFalse(self.coord._setting_requests)
        self.assertFalse(self.coord.settings_state['ctl_grid_charge'])

    async def test_eight_concurrent_requests_and_disconnect_no_replay(self):
        tasks = [asyncio.create_task(self.coord.async_write_setting('ctl_grid_charge', bool(i % 2))) for i in range(8)]
        commands = [await self.received.get() for _ in range(8)]
        self.assertEqual(len({c['requestId'] for c in commands}), 8)
        with self.assertRaisesRegex(HomeAssistantError, 'busy'):
            await self.coord.async_write_setting('ctl_grid_charge', True)
        for command in reversed(commands):
            await self.result(command)
        await asyncio.gather(*tasks)
        task = asyncio.create_task(self.coord.async_write_setting('ctl_grid_charge', True))
        await self.received.get()
        previous = len(self.sockets)
        await self.sockets[-1].close()
        with self.assertRaisesRegex(HomeAssistantError, 'connection closed'):
            await task
        async with asyncio.timeout(3):
            while len(self.sockets) == previous:
                await asyncio.sleep(.01)
        await self.ready()
        self.assertTrue(self.received.empty())
        self.assertFalse(self.coord._setting_requests)
        self.assertFalse(self.coord.settings_state['ctl_grid_charge'])

    async def test_fresh_state_and_version_gating(self):
        self.coord._reset_settings()
        self.assertFalse(self.coord.settings_available)
        self.assertFalse(self.coord.settings_state)
        self.coord._process_message(state())
        self.assertFalse(self.coord.settings_available)
        self.coord._process_message(dict(catalog(), version=2))
        self.coord._process_message(state())
        self.assertFalse(self.coord.settings_available)
        self.coord._process_message(catalog())
        self.coord._process_message(state(ctl_max_charge_current=40.05))
        self.assertEqual(self.coord.settings_state['ctl_max_charge_current'], 40.05)  # Actual readback can be off-step.
        self.coord._process_message(dict(state(), available=False))
        self.assertFalse(self.coord.settings_available)
        with self.assertRaises(HomeAssistantError):
            await self.coord.async_write_setting('ctl_grid_charge', True)
        legacy = coordinator_module.SolarProjectCoordinator(self.hass, {'server': 'http://legacy', 'device_id': ID})
        legacy._process_message({'type': 'ivtdata', 'data': {'vbat': 52.5}})
        self.assertTrue(legacy.online)
        self.assertFalse(legacy.settings_catalog)


if __name__ == '__main__':
    unittest.main()
