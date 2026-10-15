"""Register actual HA controls and invoke number/select/switch services.
Uses temporary HA configuration and a simulated dongle; no physical writes.
"""
import asyncio
from pathlib import Path
import sys
import tempfile
from types import MappingProxyType
import unittest

from aiohttp import web
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry, ConfigEntries
from homeassistant import loader
from homeassistant.components.network import async_get_network
from homeassistant.helpers import area_registry, device_registry, entity_registry, issue_registry

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_inverter_settings import ID, VALUES, catalog, state


class SettingsRuntimeTest(unittest.IsolatedAsyncioTestCase):
    async def test_services_readback_and_reload(self):
        commands = []
        sockets = []

        async def stream(request):
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            sockets.append(ws)
            for payload in [
                {'type': 'deviceStatus', 'deviceId': ID, 'status': 'online'},
                {'type': 'ivtdata', 'data': {'vbat': 52.5}}, catalog(), state(),
            ]:
                await ws.send_json(payload)
            async for message in ws:
                command = message.json()
                commands.append(command)
                await ws.send_json({'type': 'inverterSettingResult', 'deviceId': ID,
                                    'requestId': command['requestId'], 'accepted': True})
            return ws

        app = web.Application()
        app.router.add_get('/ws/' + ID, stream)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '127.0.0.1', 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        with tempfile.TemporaryDirectory(prefix='solarproject-settings-runtime-') as directory:
            root = Path(directory)
            (root / 'custom_components').mkdir()
            (root / 'custom_components/solarproject').symlink_to(
                Path(__file__).resolve().parents[1] / 'custom_components/solarproject', target_is_directory=True)
            hass = HomeAssistant(directory)
            hass.config.skip_pip = True
            loader.async_setup(hass)
            hass.config_entries = ConfigEntries(hass, {})
            await hass.config_entries.async_initialize()
            await asyncio.gather(*(registry.async_load(hass) for registry in
                                   (area_registry, device_registry, entity_registry, issue_registry)))
            try:
                await async_get_network(hass)
                entry = ConfigEntry(version=1, minor_version=1, domain='solarproject', title='Test dongle',
                                    data={'server': f'http://127.0.0.1:{port}', 'device_id': ID, 'fast_data_interval': 0},
                                    options={}, source='user', unique_id=ID,
                                    discovery_keys=MappingProxyType({}), subentries_data=[])
                await hass.config_entries.async_add(entry)
                registry = entity_registry.async_get(hass)

                async def ready():
                    async with asyncio.timeout(5):
                        while len([s for s in hass.states.async_all() if s.domain == 'number' and s.state != 'unavailable']) != 14:
                            await asyncio.sleep(.01)
                    await hass.async_block_till_done()

                await ready()
                states = hass.states.async_all()
                self.assertEqual(len([s for s in states if s.domain == 'number']), 14)
                self.assertEqual(len([s for s in states if s.domain == 'select']), 3)
                self.assertEqual(len([s for s in states if s.domain == 'switch']), 1)
                self.assertEqual(len([e for e in registry.entities.values() if e.unique_id == f'solarproject_{ID}_vbat']), 1)

                def entity_id(key, domain):
                    return registry.async_get_entity_id(domain, 'solarproject', f'solarproject_{ID}_{key}')

                # Check rendered HA names: has_entity_name=True would prepend the device name.
                for spec in catalog()['settings']:
                    registered_id = entity_id(spec['key'], spec['platform'])
                    self.assertEqual(hass.states.get(registered_id).attributes['friendly_name'], spec['name'])
                self.assertEqual(entity_id('ctl_work_mode', 'select'), 'select.dg_aabbcc_ivt_work_mode')
                current = entity_id('ctl_max_charge_current', 'number')
                mode = entity_id('ctl_work_mode', 'select')
                grid = entity_id('ctl_grid_charge', 'switch')
                # Model an existing entity ID from before the naming change.
                existing_id = 'number.my_charge_current'
                registry.async_update_entity(current, new_entity_id=existing_id)
                current = existing_id
                custom = entity_id('ctl_battery_ah', 'number')
                registry.async_update_entity(custom, name='My battery capacity')
                await hass.async_block_till_done()
                self.assertEqual(hass.states.get(current).attributes['unit_of_measurement'], 'A')
                self.assertEqual(hass.states.get(current).attributes['step'], .1)
                await hass.services.async_call('number', 'set_value', {'entity_id': current, 'value': 50.1}, blocking=True)
                await hass.services.async_call('select', 'select_option', {'entity_id': mode, 'option': 'Backup'}, blocking=True)
                await hass.services.async_call('switch', 'turn_on', {'entity_id': grid}, blocking=True)
                self.assertEqual([(c['key'], c['value']) for c in commands],
                                 [('ctl_max_charge_current', 50.1), ('ctl_work_mode', 'Backup'), ('ctl_grid_charge', True)])
                self.assertEqual(float(hass.states.get(current).state), 40.0)
                self.assertEqual(hass.states.get(mode).state, 'Self Used')
                self.assertEqual(hass.states.get(grid).state, 'off')
                await sockets[-1].send_json(state(ctl_max_charge_current=50.1, ctl_work_mode='Backup', ctl_grid_charge=True))
                async with asyncio.timeout(2):
                    while hass.states.get(grid).state != 'on':
                        await asyncio.sleep(.01)
                self.assertEqual(float(hass.states.get(current).state), 50.1)
                self.assertEqual(hass.states.get(mode).state, 'Backup')
                # Reload reuses registry IDs and cleans up discovery/entity listeners.
                await hass.config_entries.async_reload(entry.entry_id)
                await ready()
                self.assertEqual(entity_id('ctl_max_charge_current', 'number'), current)
                self.assertEqual(hass.states.get(current).attributes['friendly_name'], 'Ivt Max Charge Current')
                self.assertEqual(hass.states.get(custom).attributes['friendly_name'], 'My battery capacity')
                self.assertEqual(len([s for s in hass.states.async_all() if s.domain == 'number']), 14)
                self.assertEqual(len(commands), 3)
                await hass.config_entries.async_unload(entry.entry_id)
            finally:
                await hass.async_stop()
                await runner.cleanup()


if __name__ == '__main__':
    unittest.main()
