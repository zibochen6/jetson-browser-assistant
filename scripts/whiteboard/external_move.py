"""Independent X11 mouse test: moves Camera without touching Agent state.

Run only on the target's idle desktop. Uses libX11/libXtst already installed,
not a service edit endpoint, scene-writing API or the Agent's operation history.
"""
import argparse
import ctypes as C
import json
import os
import re
import subprocess
import time

import httpx
from jetson_browser.config import ROOT, desktop_env
from jetson_browser.whiteboard_scene import scene

os.environ.update(desktop_env())
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--content-x', type=int, required=True, help='Content origin in root-screen pixels, measured from a desktop screenshot')
parser.add_argument('--content-y', type=int, required=True)
parser.add_argument('--close-window', action='store_true', help='Send the native close-window shortcut instead of dragging')
args = parser.parse_args()
base = 'http://127.0.0.1:8793'
with httpx.Client(base_url=base, trust_env=False, timeout=10) as c:
    assert not c.get('/health').json()['active_tasks'], 'The board must be idle'
    before = c.get('/board').json()
    camera = next(v for v in scene(before)['shapes'].values() if v['text'] == 'Camera')
    windows = subprocess.check_output(['xwininfo', '-root', '-tree'], text=True)
    window = re.search(r'(0x[0-9a-f]+) "Jetson Whiteboard - Google Chrome for Testing"', windows)
    assert window, 'Expected exactly the project whiteboard window'
    x11, xtst = C.CDLL('libX11.so.6'), C.CDLL('libXtst.so.6')
    x11.XOpenDisplay.argtypes = [C.c_char_p]
    x11.XOpenDisplay.restype = C.c_void_p
    display = x11.XOpenDisplay(b':0')
    assert display
    for name in ('XFlush', 'XCloseDisplay'):
        getattr(x11, name).argtypes = [C.c_void_p]
    x11.XRaiseWindow.argtypes = [C.c_void_p, C.c_ulong]
    x11.XSetInputFocus.argtypes = [C.c_void_p, C.c_ulong, C.c_int, C.c_ulong]
    x11.XStringToKeysym.argtypes = [C.c_char_p]
    x11.XStringToKeysym.restype = C.c_ulong
    x11.XKeysymToKeycode.argtypes = [C.c_void_p, C.c_ulong]
    x11.XKeysymToKeycode.restype = C.c_uint
    xtst.XTestFakeKeyEvent.argtypes = [C.c_void_p, C.c_uint, C.c_int, C.c_ulong]
    xtst.XTestFakeButtonEvent.argtypes = [C.c_void_p, C.c_uint, C.c_int, C.c_ulong]
    xtst.XTestFakeMotionEvent.argtypes = [C.c_void_p, C.c_int, C.c_int, C.c_int, C.c_ulong]
    viewport, app = before['viewport'], before['appState']

    def screen_point(x, y):
        # Playwright viewport emulation and Mutter frame insets make outerHeight
        # unsuitable for recovering the root-screen content origin. Calibrate it
        # visibly once for this independent native-input test.
        return (int(args.content_x + app['offsetLeft'] + (x + app['scrollX']) * app['zoom']['value']),
                int(args.content_y + app['offsetTop'] + (y + app['scrollY']) * app['zoom']['value']))

    a = screen_point(camera['x'], camera['y'] + 24)
    b = screen_point(1060, 704)
    ident = int(window[1], 16)
    x11.XRaiseWindow(display, ident)
    x11.XSetInputFocus(display, ident, 2, 0)
    x11.XFlush(display)
    time.sleep(.15)
    if args.close_window:
        codes = [x11.XKeysymToKeycode(display, x11.XStringToKeysym(key)) for key in (b'Control_L', b'Shift_L', b'w')]
        for code in codes:
            xtst.XTestFakeKeyEvent(display, code, 1, 0)
        for code in reversed(codes):
            xtst.XTestFakeKeyEvent(display, code, 0, 0)
        x11.XFlush(display)
        x11.XCloseDisplay(display)
        time.sleep(.5)
        health = c.get('/health').json()
        (ROOT / 'runtime/whiteboard-window-close-check.json').write_text(json.dumps(health, indent=2))
        print(json.dumps(health))
        assert not health['browser_open']
        raise SystemExit(0)
    for key in (b'Escape', b'Escape', b'v'):
        code = x11.XKeysymToKeycode(display, x11.XStringToKeysym(key))
        xtst.XTestFakeKeyEvent(display, code, 1, 0)
        xtst.XTestFakeKeyEvent(display, code, 0, 0)
    xtst.XTestFakeMotionEvent(display, -1, *a, 0)
    xtst.XTestFakeButtonEvent(display, 1, 1, 0)
    x11.XFlush(display)
    time.sleep(.05)
    try:
        for i in range(1, 25):
            point = [int(a[j] + (b[j] - a[j]) * i / 24) for j in (0, 1)]
            xtst.XTestFakeMotionEvent(display, -1, *point, 0)
            x11.XFlush(display)
            time.sleep(.015)
    finally:
        xtst.XTestFakeButtonEvent(display, 1, 0, 0)
        x11.XFlush(display)
        x11.XCloseDisplay(display)
    time.sleep(.3)
    after = c.get('/board').json()
    moved = scene(after)['shapes'][camera['id']]
    report = {'method': 'independent native X11/XTest mouse gesture; no Agent cache or scene writes',
        'before': before, 'after': after, 'screen_start': a, 'screen_end': b,
        'passed': abs(moved['x'] - camera['x']) > 100 and abs(moved['y'] - camera['y']) > 100}
    (ROOT / 'runtime/whiteboard-external-move.json').write_text(json.dumps(report, indent=2))
    print(json.dumps({'passed': report['passed'], 'before': [camera['x'], camera['y']], 'after': [moved['x'], moved['y']]}))
    assert report['passed'], 'Native drag did not move the actual Camera object'
