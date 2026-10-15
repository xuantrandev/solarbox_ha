"""Exercise real HA sensor platforms against a simulated legacy WebSocket."""
import asyncio
from pathlib import Path
import sys
import tempfile
from types import MappingProxyType
import unittest
from aiohttp import web
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.config_entries import ConfigEntry, ConfigEntries
from homeassistant import loader
from homeassistant.components.network import async_get_network
from homeassistant.helpers import area_registry, device_registry, entity_registry, issue_registry

ID='dg-aabbcc'
class RuntimeTest(unittest.IsolatedAsyncioTestCase):
 async def test_sensor_platforms(self):
  requests=[]
  sockets=[]
  async def stream(request):
   ws=web.WebSocketResponse();await ws.prepare(request)
   sockets.append(ws)
   for payload in [
    {'type':'deviceStatus','deviceId':ID,'status':'online'},
    {'type':'ivtdata','data':{'vbat':52.5,'pdc1':120,'pvtd':2300}},
    {'type':'bmsData','bmsType':'bms1','data':{'vbat':525,'cur':-109,'p':-572,'chg':1,'dischg':0,'vcells':[3279,3280]}},
    {'type':'bmsData','bmsType':'bms2','data':{'p':125.25,'chg':0,'dischg':1}},
   ]:await ws.send_json(payload)
   async for message in ws:requests.append(message.json())
   return ws
  app=web.Application();app.router.add_get('/ws/'+ID,stream);runner=web.AppRunner(app);await runner.setup()
  site=web.TCPSite(runner,'127.0.0.1',0);await site.start();port=site._server.sockets[0].getsockname()[1]
  with tempfile.TemporaryDirectory(prefix='solarproject-ha-runtime-') as directory:
   root=Path(directory);(root/'custom_components').mkdir()
   (root/'custom_components/solarproject').symlink_to(Path(__file__).resolve().parents[1]/'custom_components/solarproject',target_is_directory=True)
   hass=HomeAssistant(directory);hass.config.skip_pip=True;loader.async_setup(hass)
   hass.config_entries=ConfigEntries(hass,{});await hass.config_entries.async_initialize()
   if setup_devices:=getattr(device_registry,'async_setup',None):setup_devices(hass)
   await asyncio.gather(*(registry.async_load(hass) for registry in
                         (area_registry,device_registry,entity_registry,issue_registry)))
   try:
    await async_get_network(hass)
    entry=ConfigEntry(version=1,minor_version=1,domain='solarproject',title='Test dongle',
      data={'server':f'http://127.0.0.1:{port}','device_id':ID,'fast_data_interval':0},
      options={},source='user',unique_id=ID,discovery_keys=MappingProxyType({}),subentries_data=[])
    await hass.config_entries.async_add(entry)
    for _ in range(200):
     if len([s for s in hass.states.async_all() if 'cell_voltage' in s.entity_id])>=2:break
     await asyncio.sleep(.02)
    await hass.async_block_till_done()
    states=hass.states.async_all()
    self.assertEqual({s.domain for s in states},{'sensor','binary_sensor','switch'})
    self.assertEqual(len(hass.states.async_all('switch')),6)
    for slot,charging,discharging in [(1,'on','off'),(2,'off','on'),(3,'unknown','unknown')]:
     for direction,expected in [('charging',charging),('discharging',discharging)]:
      self.assertEqual(hass.states.get(f'switch.dg_aabbcc_bms{slot}_{direction}').state,expected)
    for suffix,value in [('bms1_total_voltage',52.5),('bms1_current',-10.9),('bms1_cell_voltage_1',3.279),('ivt_pv1_power',120),('ivt_pv_today_lux',2.3),('bms1_power',-572),('bms1_charging_power',0),('bms1_discharging_power',572),('bms2_charging_power',125.25),('bms2_discharging_power',0)]:
     state=next(s for s in states if s.entity_id.endswith(suffix))
     self.assertEqual(float(state.state),value)
    self.assertEqual(next(s for s in states if s.entity_id.endswith('ivt_pv_today_lux')).attributes['state_class'],'total_increasing')
    self.assertEqual(next(s for s in states if s.entity_id.endswith('ivt_pv_today_lux')).attributes['unit_of_measurement'],'kWh')
    for slot in (1,2,3):
     for direction in ('charging','discharging'):
      state=hass.states.get(f'sensor.dg_aabbcc_bms{slot}_{direction}_power')
      self.assertIsNotNone(state)
      self.assertEqual(state.attributes['unit_of_measurement'],'W')
      self.assertEqual(state.attributes['device_class'],'power')
      self.assertEqual(state.attributes['state_class'],'measurement')
      if slot==3:self.assertEqual(state.state,'unknown')
    # Updates must clear the old direction, retain fractions, and isolate slots.
    for slot,power in [(1,310.125),(1,-200.5),(1,0),(3,-42.75),(3,90),(3,0)]:
     with self.subTest(slot=slot,power=power):
      await sockets[-1].send_json({'type':'bmsData','bmsType':f'bms{slot}','data':{'p':power}})
      expected=(max(power,0),max(-power,0))
      async with asyncio.timeout(5):
       while tuple(hass.states.get(f'sensor.dg_aabbcc_bms{slot}_{direction}_power').state for direction in ('charging','discharging'))!=tuple(str(float(value)) for value in expected):
        await asyncio.sleep(.01)
      self.assertEqual(float(hass.states.get('sensor.dg_aabbcc_bms2_charging_power').state),125.25)
    # Reported MOS states can both be on even when there is no power flow.
    await sockets[-1].send_json({'type':'bmsData','bmsType':'bms3','data':{'chg':1,'dischg':1}})
    async with asyncio.timeout(5):
     while any(hass.states.get(f'switch.dg_aabbcc_bms3_{direction}').state!='on' for direction in ('charging','discharging')):
      await asyncio.sleep(.01)
    for direction in ('charging','discharging'):
     entity_id=f'switch.dg_aabbcc_bms3_{direction}'
     for service in ('turn_on','turn_off','toggle'):
      with self.assertRaisesRegex(HomeAssistantError,'read-only'):
       await hass.services.async_call('switch',service,{'entity_id':entity_id},blocking=True)
      self.assertEqual(hass.states.get(entity_id).state,'on')
    await sockets[-1].send_json({'type':'bmsData','bmsType':'bms3','data':{'chg':0,'dischg':0}})
    async with asyncio.timeout(5):
     while any(hass.states.get(f'switch.dg_aabbcc_bms3_{direction}').state!='off' for direction in ('charging','discharging')):
      await asyncio.sleep(.01)
    registry=entity_registry.async_get(hass)
    for key,name in {
     'vbat':'Ivt Battery Voltage', 'bcur':'Ivt Battery Current Lux', 'pbat':'Ivt Battery Power Lux',
     'pvtd':'Ivt PV Today Lux', 'pvall':'Ivt PV Total Lux', 'ech':'Ivt Battery Charge Today Lux',
     'pl1':'Ivt Load L1 Power', 'bms1_vbat':'bms1 total voltage',
     'bms1_charging_power':'bms1 charging power', 'bms1_discharging_power':'bms1 discharging power',
     'bms1_vcells_1':'bms1 cell voltage 1', 'bms1_connected':'bms1 online status',
    }.items():
     domain='binary_sensor' if key=='bms1_connected' else 'sensor'
     registered_id=registry.async_get_entity_id(domain,'solarproject',f'solarproject_{ID}_{key}')
     self.assertEqual(registry.async_get(registered_id).original_name,name)
     self.assertTrue(hass.states.get(registered_id).attributes['friendly_name'].endswith(name))
    self.assertEqual(registry.async_get_entity_id('sensor','solarproject',f'solarproject_{ID}_vbat'),'sensor.dg_aabbcc_ivt_battery_voltage')
    cells=[e for e in registry.entities.values() if e.unique_id=='solarproject_dg-aabbcc_bms1_vcells_1']
    self.assertEqual(len(cells),1)
    self.assertFalse(requests)
    await sockets[-1].send_json({'type':'deviceStatus','deviceId':ID,'status':'offline'})
    async with asyncio.timeout(5):
     while hass.states.get('switch.dg_aabbcc_bms1_charging').state!='unavailable':
      await asyncio.sleep(.01)
    await hass.config_entries.async_unload(entry.entry_id)
   finally:
    await hass.async_stop();await runner.cleanup()
if __name__=='__main__':unittest.main()
