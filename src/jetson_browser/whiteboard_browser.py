"""UI-only Excalidraw edits; public APIs are used only for reads and exports."""
import base64
import asyncio
import json
from pathlib import Path

from .browser import Browser, StaleObservation
from .config import ROOT
from .whiteboard_scene import digest, scene

URL = 'http://127.0.0.1:8793/whiteboard/'


class WhiteboardBrowser(Browser):
    def __init__(self, **kwargs):
        super().__init__(profile_dir=ROOT / 'runtime/whiteboard-profile', **kwargs)
        self.receipt = None
        self.board_page = None

    async def open(self):
        await self.start()
        if self.board_page is not self.page or not self.page.url.startswith(URL):
            # Chromium can restore an old document from the persistent profile.
            # Load this build once, while retaining the scene through local autosave.
            index = ROOT / 'src/jetson_browser/static/whiteboard/index.html'
            await self.navigate(URL + '?build=' + digest(index.read_text())[:12])
            await self.page.set_viewport_size({'width': 1440, 'height': 1000})
            if not self.headless:
                from .presentation import desktop_layout, window_bounds
                available = desktop_layout()['site']
                await window_bounds(self.context, self.page, {'left': available['left'] + 32,
                    'top': available['top'] + 48, 'width': 1472, 'height': 1136})
            self.board_page = self.page
        await self.page.wait_for_function('()=>!!window.whiteboard', timeout=30000)
        await self.page.bring_to_front()

    async def read(self):
        if not self.is_open():
            raise RuntimeError('Whiteboard window was closed; submit a new task to reopen it')
        return await asyncio.wait_for(self.page.evaluate('whiteboard.read()'), timeout=5)

    async def release(self):
        if not self.is_open():
            return True
        page = self.page
        async def cleanup():
            await page.mouse.up()
            for key in ('Control', 'Shift', 'Alt', 'Meta'):
                await page.keyboard.up(key)
        try:
            await asyncio.wait_for(cleanup(), timeout=2)
            return True
        except Exception:
            return False

    def note(self, kind, **data):
        if self.receipt:
            self.receipt(kind, data)

    async def tool(self, name):
        locator = self.page.get_by_test_id('toolbar-' + name).locator('..')
        await locator.click()
        self.note('toolbar_click', tool=name)

    async def key(self, key):
        await self.page.keyboard.press(key)
        self.note('keyboard_shortcut', key=key)

    async def drag(self, a, b):
        await self.page.mouse.move(*a)
        await self.page.mouse.down()
        try:
            await self.page.mouse.move(*b, steps=18)
        finally:
            await self.page.mouse.up()
        self.note('mouse_drag', start=list(a), end=list(b), coordinate_space='browser CSS pixels')

    def point(self, raw, x, y):
        s = raw['appState']
        z = s['zoom']['value']
        px = (x + s['scrollX']) * z + s['offsetLeft']
        py = (y + s['scrollY']) * z + s['offsetTop']
        if not (260 < px < 1430 and 100 < py < 960):
            raise ValueError('The target is outside the supported viewport; restore 100% zoom and the original view')
        return (px, py)

    async def select(self, raw, target):
        await self.key('Escape')
        await self.tool('selection')
        s = scene(raw)['shapes'][target]
        # Use the left border, away from bound text and the center resize handle.
        xy = self.point(raw, s['x'] + (s['width'] / 2 if s['kind'] == 'text' else 0),
                        s['y'] + (s['height'] / 2 if s['kind'] == 'text' else 24))
        await self.page.mouse.click(*xy)
        self.note('object_click', target=target, point=list(xy))
        await self.page.wait_for_function('(id)=>!!whiteboard.read().appState.selectedElementIds[id]', arg=target, timeout=2500)

    async def color(self, raw, target, value):
        await self.select(raw, target)
        swatch = self.page.get_by_test_id('color-top-pick-' + value)
        await swatch.click()
        self.note('property_click', target=target, property='color', value=value)

    async def label(self, raw, target, text):
        shape = scene(raw)['shapes'][target]
        await self.key('Escape')
        await self.tool('selection')
        await self.page.mouse.dblclick(*self.point(raw, shape['x'] + shape['width'] / 2, shape['y'] + shape['height'] / 2))
        self.note('pointer_double_click', target=target, purpose='edit text')
        editor = self.page.locator('textarea.excalidraw-wysiwyg')
        await editor.wait_for(state='visible', timeout=3000)
        await editor.focus()
        await self.key('Control+A')
        await self.page.keyboard.insert_text(text)
        self.note('text_input', target=target, text=text)
        await self.key('Escape')

    async def delete_arrow(self, raw, target):
        arrow = next(e for e in raw['elements'] if e['id'] == target)
        await self.key('Escape')
        await self.tool('selection')
        pts = arrow['points']
        a, b = max(zip(pts, pts[1:]), key=lambda pair: (pair[1][0]-pair[0][0])**2 + (pair[1][1]-pair[0][1])**2)
        await self.page.mouse.click(*self.point(raw, arrow['x'] + (a[0]+b[0])/2, arrow['y'] + (a[1]+b[1])/2))
        self.note('arrow_click', target=target)
        await self.page.wait_for_function('(id)=>!!whiteboard.read().appState.selectedElementIds[id]', arg=target, timeout=2000)
        await self.key('Delete')

    async def execute(self, observation, action):
        raw = await self.read()
        if digest(raw) != digest(observation):
            raise StaleObservation('The whiteboard changed during the model request; re-observing before any input')
        current = scene(raw)
        op = action['op']
        try:
            if op == 'create':
                want = action['desired']
                old_ids = {e['id'] for e in raw['elements']}
                await self.key('Escape')
                await self.tool('rectangle' if want['kind'] == 'rectangle' else 'text')
                if want['kind'] == 'rectangle':
                    # Initialize new-object defaults through visible properties.
                    await self.page.get_by_test_id('color-top-pick-#1e1e1e').click()
                    self.note('property_click', property='new_object_stroke', value='#1e1e1e')
                    await self.page.get_by_test_id('color-top-pick-transparent').click()
                    self.note('property_click', property='new_object_background', value='transparent')
                    await self.drag(self.point(raw, want['x'], want['y']), self.point(raw, want['x'] + 200, want['y'] + 112))
                    fresh = await self.read()
                    new = [e for e in fresh['elements'] if e['id'] not in old_ids and e['type'] == 'rectangle']
                    if len(new) != 1:
                        raise RuntimeError('Rectangle creation did not produce exactly one new object')
                    await self.label(fresh, new[0]['id'], want['text'])
                else:
                    await self.page.mouse.click(*self.point(raw, want['x'], want['y']))
                    self.note('text_placement_click', scene_point=[want['x'], want['y']])
                    editor = self.page.locator('textarea.excalidraw-wysiwyg')
                    await editor.wait_for(state='visible')
                    await self.page.keyboard.insert_text(want['text'])
                    self.note('text_input', text=want['text'])
                    await self.key('Escape')
            elif op == 'select':
                await self.select(raw, action['target'])
            elif op == 'recolor':
                await self.color(raw, action['target'], action['color'])
                await self.key('Escape')
            elif op == 'rename':
                await self.label(raw, action['target'], action['text'])
            elif op == 'move':
                await self.select(raw, action['target'])
                s = current['shapes'][action['target']]
                dx, dy = (s['width'] / 2, s['height'] / 2) if s['kind'] == 'text' else (0, 24)
                await self.drag(self.point(raw, s['x'] + dx, s['y'] + dy), self.point(raw, action['x'] + dx, action['y'] + dy))
                await self.key('Escape')
            elif op == 'connect':
                a, b = current['shapes'][action['source_id']], current['shapes'][action['destination_id']]
                if a['kind'] != 'rectangle' or b['kind'] != 'rectangle':
                    raise ValueError('Arrow binding currently supports rectangles only')
                await self.key('Escape')
                await self.tool('arrow')
                dx = b['x'] - a['x']
                dy = b['y'] - a['y']
                if abs(dx) >= abs(dy):
                    left, right = (a, b) if dx > 0 else (b, a)
                    start = (left['x'] + left['width'] + 4, left['y'] + left['height'] / 2)
                    end = (right['x'] - 4, right['y'] + right['height'] / 2)
                    if dx < 0:
                        start, end = end, start
                else:
                    upper, lower = (a, b) if dy > 0 else (b, a)
                    start = (upper['x'] + upper['width'] / 2, upper['y'] + upper['height'] + 4)
                    end = (lower['x'] + lower['width'] / 2, lower['y'] - 4)
                    if dy < 0:
                        start, end = end, start
                await self.drag(self.point(raw, *start), self.point(raw, *end))
                await self.key('Escape')
            elif op in ('delete', 'delete_arrow'):
                if op == 'delete':
                    for edge in current['edges'].values():
                        if action['target'] in (edge['source'], edge['destination']):
                            await self.delete_arrow(await self.read(), edge['id'])
                    await self.select(await self.read(), action['target'])
                    await self.key('Delete')
                else:
                    await self.delete_arrow(raw, action['target'])
            else:
                raise ValueError('Unsupported whiteboard capability')
        finally:
            await self.release()

    async def export(self, folder):
        folder = Path(folder)
        before = await self.read()
        editable = await self.page.evaluate('whiteboard.scene()')
        (folder / 'scene.excalidraw').write_text(editable)
        png = await self.page.evaluate('whiteboard.png()')
        data = base64.b64decode(png.split(',', 1)[1])
        if not data.startswith(b'\x89PNG\r\n\x1a\n'):
            raise RuntimeError('Export did not return PNG bytes')
        (folder / 'canvas.png').write_bytes(data)
        await self.screenshot(folder / 'screenshot.png')
        after = await self.read()
        if not (digest(before['elements']) == digest(json.loads(editable)['elements']) == digest(after['elements'])):
            raise RuntimeError('Canvas changed during export; files retained but not accepted as a verified snapshot')
        return {'editable': str(folder / 'scene.excalidraw'), 'image': str(folder / 'canvas.png'), 'screenshot': str(folder / 'screenshot.png')}

    async def import_file(self, path):
        await self.open()
        expected = json.loads(Path(path).read_text())
        if expected.get('type') != 'excalidraw':
            raise ValueError('Expected an Excalidraw scene file')
        # This is an explicit file-open operation, never a drawing shortcut.
        await self.page.get_by_test_id('open-scene-file').set_input_files(str(Path(path).resolve()))
        expected_ids = sorted(e['id'] for e in expected['elements'] if not e.get('isDeleted'))
        await self.page.wait_for_function('(ids)=>JSON.stringify(whiteboard.read().elements.map(e=>e.id).sort())===JSON.stringify(ids)', arg=expected_ids, timeout=10000)
        return await self.read()
