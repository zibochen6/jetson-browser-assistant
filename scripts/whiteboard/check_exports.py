"""Check real saved PNG payloads, editable-file reopening and archived events."""
import json
import struct
import sys
import zlib

import httpx
from jetson_browser.config import ROOT
from jetson_browser.whiteboard_scene import Goal, compile_goal, scene, verify


def png_payload(path):
    data = path.read_bytes()
    assert data[:8] == b'\x89PNG\r\n\x1a\n'
    pos, compressed, header = 8, bytearray(), None
    while pos < len(data):
        size = struct.unpack('>I', data[pos:pos+4])[0]
        kind, payload = data[pos+4:pos+8], data[pos+8:pos+8+size]
        crc = struct.unpack('>I', data[pos+8+size:pos+12+size])[0]
        assert zlib.crc32(kind+payload) & 0xffffffff == crc
        if kind == b'IHDR':
            header = struct.unpack('>IIBBBBB', payload)
        if kind == b'IDAT':
            compressed.extend(payload)
        pos += size+12
        if kind == b'IEND':
            break
    width,height,depth,color,compression,filtering,interlace = header
    assert width>10 and height>10 and depth==8 and color in (2,6) and interlace==0
    channels = 4 if color==6 else 3
    decoded = zlib.decompress(compressed)
    stride = width*channels+1
    assert len(decoded)==height*stride
    assert all(decoded[row*stride] <= 4 for row in range(height))
    return {'width':width,'height':height,'color_type':color,'decompressed_bytes':len(decoded),
            'crc_and_scanlines':'PASS'}


run_id = sys.argv[1]
folder = ROOT / 'whiteboard-runs' / run_id
saved = json.loads((folder/'scene.excalidraw').read_text())
baseline = scene({'elements':saved['elements'],'appState':{'selectedElementIds':{}}})
contract = compile_goal(Goal(changes=[],needs_clarification=False,clarification=''),baseline)
with httpx.Client(base_url='http://127.0.0.1:8793',timeout=40,trust_env=False) as client:
    assert not client.get('/health').json()['active_tasks']
    r=client.post('/open',json={'path':str(folder/'scene.excalidraw')});r.raise_for_status()
    actual=client.get('/board').json()
    report=verify(contract,scene(actual))
    assert report['passed'], report
    cursor,events=0,[]
    while True:
        r=client.get(f'/tasks/{run_id}/events',params={'after':cursor});r.raise_for_status();batch=r.json()
        events.extend(batch['events'])
        assert batch['next_cursor']==cursor+len(batch['events'])
        cursor=batch['next_cursor']
        if not batch['events']: break
    assert [e['sequence'] for e in events]==list(range(len(events)))
    result={'run_id':run_id,'status':'PASS','png':png_payload(folder/'canvas.png'),
        'reopened_scene_verification':report,'archive_event_count':len(events)}
    (ROOT/'runtime'/f'whiteboard-export-check-{run_id}.json').write_text(json.dumps(result,indent=2))
    print(json.dumps({'run_id':run_id,'status':'PASS','png':result['png'],'archive_events':len(events)}))
