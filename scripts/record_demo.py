"""Uncut original-speed X11 capture including a real terminal submitting the CLI."""
from datetime import datetime
import json
import subprocess
import time

import httpx

from jetson_browser.config import ROOT, desktop_env, settings
from jetson_browser.llm import local_url
from jetson_browser.recording import Recording

folder = ROOT / 'evidence' / ('demo-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
folder.mkdir(parents=True)
with httpx.Client(base_url=local_url(settings()['service_url']), trust_env=False, timeout=40) as client:
    try:
        health = client.get('/health', timeout=2).raise_for_status().json()
    except httpx.ConnectError:
        health = {'active_tasks': []}  # Cold-start capture: the CLI will start services itself.
    if health['active_tasks']:
        raise SystemExit('Another task is active')
    env = desktop_env()
    env.setdefault('DBUS_SESSION_BUS_ADDRESS', 'unix:path=/run/user/1000/bus')
    recording = Recording(folder, wide=True)
    error = recording.start()
    if error:
        raise SystemExit(error)
    started = time.time()
    try:
        time.sleep(1)
        # X11 capture must use an X11 terminal, independent of a desktop's
        # existing Wayland/D-Bus terminal instance.
        process = subprocess.Popen(['xterm', '-u8', '-fa', 'DejaVu Sans Mono', '-fs', '13',
                                    '-geometry', '100x44+1480+40', '-T', 'Jetson Browser - real CLI',
                                    '-e', 'bash', str(ROOT / 'scripts/demo_command.sh'), str(folder)], env=env)
        (folder / 'terminal-process.json').write_text(json.dumps({'pid': process.pid, 'terminal': 'xterm (X11)'}))
        while not (folder / 'exit-code.txt').exists() and time.time() - started < 750:
            time.sleep(1)
        if not (folder / 'exit-code.txt').exists():
            for task_id in client.get('/health').raise_for_status().json()['active_tasks']:
                client.post('/tasks/' + task_id + '/cancel').raise_for_status()
            raise RuntimeError('Demo did not finish; capture retained, not a successful demonstration')
        time.sleep(5)
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'x11grab',
                        '-video_size', '3840x1440', '-i', env['DISPLAY'] + '.0+0,0', '-frames:v', '1',
                        str(folder / 'desktop-final.png')], env=env, check=True, timeout=20)
    finally:
        error = recording.stop()
        (folder / 'capture.json').write_text(json.dumps({'started_at': started, 'wall_seconds': time.time()-started,
            'error': error, 'original_speed': True, 'edited': False, 'source': 'X11 desktop, real xterm + visible Chromium'}, indent=2))
    probe = subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration,size:stream=codec_name,width,height,r_frame_rate,nb_frames', '-of', 'json', str(folder / 'desktop.mp4')], text=True)
    (folder / 'ffprobe.json').write_text(probe)
    print(folder, 'CLI exit', (folder / 'exit-code.txt').read_text().strip(), flush=True)
