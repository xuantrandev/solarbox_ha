"""Run with the Home Assistant Docker image; no live HA config is modified.
See custom_components/solarproject/README.md for the command.
"""
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from aiohttp import ClientSession, web

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from custom_components.solarproject import coordinator as coordinator_module
from custom_components.solarproject import config_flow, sensor
from custom_components.solarproject.const import DOMAIN


class LocalWebSocketTest(unittest.IsolatedAsyncioTestCase):
    async def test_local_stream_cells_and_reconnect(self):
        payloads = [
            {"type": "deviceStatus", "status": "online", "deviceId": "dg-aabbcc"},
            {"type": "ivtdata", "datatype": "invtlive", "data": {"vbat": 52.5, "pdc1": 120}},
            {"type": "ivtdata", "datatype": "invtstatis", "data": {"pvall": 1000}},
            {"type": "bmsData", "bmsType": "bms1", "data": {"vbat": 525, "cur": -109, "vcells": [3279, 3280]}},
            {"type": "wifiSignal", "data": {"signal": -60}},
        ]
        sockets, received = [], []
        async def stream(request):
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            sockets.append(ws)
            for payload in payloads:
                await ws.send_json(payload)
            async for message in ws:
                received.append(json.loads(message.data))
            return ws
        app = web.Application()
        app.router.add_get('/ws/dg-aabbcc', stream)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '127.0.0.1', 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        tasks = []
        def create_task(coro, **kwargs):
            task = asyncio.create_task(coro, **kwargs)
            tasks.append(task)
            return task
        hass = SimpleNamespace(data={}, async_create_task=create_task)
        entry = SimpleNamespace(entry_id='test', data={}, async_on_unload=lambda callback: None)
        config = {'server': f'http://127.0.0.1:{port}', 'device_id': 'dg-aabbcc', 'fast_data_interval': 0}
        coord = coordinator_module.SolarProjectCoordinator(hass, config)
        hass.data[DOMAIN] = {entry.entry_id: coord}
        entities = []
        def add_entities(new_entities):
            entities.extend(new_entities)  # Real HA callback is synchronous and returns None.
        async with ClientSession() as session:
            with patch.object(coordinator_module, 'async_get_clientsession', return_value=session), \
                 patch.object(config_flow, 'async_get_clientsession', return_value=session):
                try:
                    await config_flow._validate_connection(hass, config['server'], config['device_id'])
                    await sensor.async_setup_entry(hass, entry, add_entities)
                    await coord.async_start()
                    for _ in range(100):
                        if coord.data.get('bms1_cell_count') == 2:
                            break
                        await asyncio.sleep(.02)
                    await asyncio.sleep(.05)
                    cells = [e for e in entities if isinstance(e, sensor.BmsCellSensor)]
                    self.assertEqual([e.native_value for e in cells], [3.279, 3.28])
                    self.assertEqual(sensor.BmsScalarSensor(coord, 1, 'vbat', entry).native_value, 52.5)
                    self.assertEqual(sensor.BmsScalarSensor(coord, 1, 'cur', entry).native_value, -10.9)
                    self.assertEqual(sensor.SolarSensorEntity(coord, 'pdc1', entry).native_value, 120)
                    self.assertTrue(coord.online)
                    self.assertFalse(received)  # interval=0 receives local pushes without sending requests.
                    previous = len(sockets)
                    await sockets[-1].close()
                    for _ in range(600):
                        if len(sockets) > previous and coord.online:
                            break
                        await asyncio.sleep(.02)
                    self.assertGreater(len(sockets), previous)
                    self.assertTrue(coord.online)
                    self.assertEqual(len([e for e in entities if isinstance(e, sensor.BmsCellSensor)]), 2)
                    await coord.async_stop()
                    for task in tasks:
                        if not task.cancelled() and task.done():
                            self.assertIsNone(task.exception())
                finally:
                    await coord.async_stop()
                    await runner.cleanup()


if __name__ == '__main__':
    unittest.main()
