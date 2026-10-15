"""Read-only ESP32 WebSocket checks; requires both local client slots free."""
import argparse
import asyncio
from collections import Counter
import json
import aiohttp

async def snapshot(ws, device_id, seconds):
    latest, types = {}, Counter()
    deadline=asyncio.get_running_loop().time()+seconds
    while asyncio.get_running_loop().time()<deadline:
        try: message=await ws.receive(timeout=min(2,max(.1,deadline-asyncio.get_running_loop().time())))
        except TimeoutError: continue
        if message.type==aiohttp.WSMsgType.PING:
            await ws.pong(message.data);continue
        if message.type!=aiohttp.WSMsgType.TEXT:
            if message.type in (aiohttp.WSMsgType.CLOSED,aiohttp.WSMsgType.ERROR):raise AssertionError('Device disconnected')
            continue
        assert len(message.data.encode())<=4096
        data=json.loads(message.data);kind=data['type'];types[kind]+=1
        assert data.get('deviceId')==device_id
        assert kind in ('ivtdata','bmsData','deviceStatus','deviceInfo','wifiSignal','bms1ConnectionState','bms2ConnectionState','bms3ConnectionState')
        key=kind
        if kind=='bmsData':
            assert data['bmsType'] in ('bms1','bms2','bms3');key+=':'+data['bmsType']
        if kind=='ivtdata':key+=':'+data['datatype']
        latest[key]=data
    return latest,types

async def main(args):
    url=args.server.replace('http://','ws://').replace('https://','wss://').rstrip('/')+'/ws/'+args.device_id
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
        async with session.ws_connect(url,autoping=False,max_msg_size=4096) as first:
            latest,types=await snapshot(first,args.device_id,args.seconds)
            assert latest['deviceStatus']['status']=='online'
            assert 'ivtdata:invtlive' in latest,latest.keys()
            assert any(k.startswith('bmsData:') for k in latest),latest.keys()
            await first.send_str('{malformed')
            await first.send_json({'type':'requestDataUpdate','deviceId':'dg-ffffff'})
            # An unknown command must not execute or emit command responses.
            await first.send_json({'type':'haEntityCommand','deviceId':args.device_id,'entityId':'unknown','action':'press'})
            await first.ping(b'local-ws-test')
            async with asyncio.timeout(5):
                while True:
                    message=await first.receive()
                    if message.type==aiohttp.WSMsgType.PONG:
                        assert message.data==b'local-ws-test';break
            async with session.ws_connect(url) as second:
                replay,_=await snapshot(second,args.device_id,3)
                assert 'deviceInfo' in replay and 'ivtdata:invtlive' in replay
                try:
                    async with session.ws_connect(url):raise AssertionError('Third client admitted')
                except aiohttp.WSServerHandshakeError as err:assert err.status==503,err.status
            await asyncio.sleep(.2)
            async with session.ws_connect(url) as reconnected:
                replay,_=await snapshot(reconnected,args.device_id,3)
                assert 'ivtdata:invtlive' in replay
        try:
            async with session.ws_connect(url.rsplit('/',1)[0]+'/dg-ffffff'):raise AssertionError('Foreign device ID admitted')
        except aiohttp.WSServerHandshakeError as err:assert err.status==404,err.status
    print(json.dumps({'message_types':dict(types),'project_version':latest.get('deviceInfo',{}).get('data',{}).get('project_version'),
        'inverter_battery_voltage':latest['ivtdata:invtlive']['data'].get('vbat'),
        'bms_voltages_raw':{k:v['data'].get('vbat') for k,v in latest.items() if k.startswith('bmsData:')},
        'heartbeat':'passed','client_limit':'passed','reconnect_replay':'passed','invalid_id':'passed'},ensure_ascii=False))

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--server',required=True);parser.add_argument('--device-id',required=True)
    parser.add_argument('--seconds',type=int,default=30)
    asyncio.run(main(parser.parse_args()))
