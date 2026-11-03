"""Visible Chromium, semantic observation, and observation-bound execution."""
import hashlib
import asyncio
from contextlib import nullcontext
import base64
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from playwright.async_api import async_playwright, Error as PlaywrightError, TimeoutError as PlaywrightTimeout

from .config import ROOT, desktop_env

CARD_FINGERPRINT_JS = r'''e=>{const c=e.closest('[data-jb-card]');return c?JSON.stringify({routes:[...c.querySelectorAll('[aria-label^="Flight departing from"]')].map(x=>x.getAttribute('aria-label')),price:c.querySelector('[aria-label^="One-way price:"]')?.getAttribute('aria-label')||'',airlines:[...c.querySelectorAll('[data-testid="flights-name"]')].map(x=>x.textContent)}):null;}'''

STATE_JS = r'''e=>{if(!e)return null;return {checked:typeof e.checked==='boolean'?e.checked:e.getAttribute('aria-checked'),selected:e.getAttribute('aria-selected'),expanded:e.getAttribute('aria-expanded'),value:e.value||'',card_fingerprint:(__CARD_FINGERPRINT__)(e)};}'''.replace('__CARD_FINGERPRINT__', CARD_FINGERPRINT_JS)

PROGRESS_JS = r'''old=>{
 if(location.href!==old.url)return 'url_changed';
 if(old.scroll&&(scrollX!==old.scroll[0]||scrollY!==old.scroll[1]))return 'scroll_changed';
 if(old.node){
   const e=document.querySelector('[data-jb-node="'+old.node+'"]');
   if(!e)return 'target_removed';
   const s=(__STATE__)(e);
   if(['checked','selected','expanded','value','card_fingerprint'].some(k=>s[k]!==old.state[k]))return 'target_state_changed';
 }
 if(document.body.innerText.slice(0,10000)!==old.text)return 'page_text_changed';
 return false;
}'''.replace('__STATE__', STATE_JS)

CONTROLS_JS = r"""(scope) => {
 for(const e of document.querySelectorAll('[data-jb-node]'))e.removeAttribute('data-jb-node');
 const visible = e => {const r=e.getBoundingClientRect(); const s=getComputedStyle(e); if(!(r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'))return false; const x=r.x+r.width/2,y=r.y+r.height/2; if(x>=0&&y>=0&&x<innerWidth&&y<innerHeight){const top=document.elementFromPoint(x,y);if(top&&top!==e&&!e.contains(top)&&!top.contains(e))return false;}return true;};
 const clean = s => (s||'').replace(/\s+/g,' ').trim();
 const out=[]; let seq=0;
 const core='input:not([type=hidden]),textarea,button,select,a[href],[role=button],[role=combobox],[role=option],[role=listitem][tabindex],[role=checkbox],[role=radio],[role=tab],[role=menuitem],[contenteditable=true]';
 const native=[...document.querySelectorAll(core)];
 const inCityField=e=>{let p=e;for(let i=0;p&&i<5;i++,p=p.parentElement){if(p.querySelector('input[role=combobox]')&&p.querySelectorAll('input[role=combobox]').length===1)return true;}return false;};
 const custom=[...document.querySelectorAll('div,span,li')].filter(e=>{const text=clean(e.innerText);return text&&text.length<=180&&getComputedStyle(e).cursor==='pointer'&&!e.closest(core)&&!inCityField(e)&&visible(e);});
 const candidates=[...new Set([...native,...custom.filter(e=>!custom.includes(e.parentElement)||clean(e.parentElement.innerText)!==clean(e.innerText))])];
 let roots=[];
 if(scope==='flight_form'){
   let form=document.querySelector('input[aria-label="Departure airport or city"]');
   const hasSearch=p=>[...p.querySelectorAll('button,[role=button],[data-testid]')].some(e=>clean(e.getAttribute('aria-label')||e.getAttribute('title')||e.innerText)==='Search');
   while(form&&form!==document.body&&!hasSearch(form))form=form.parentElement;
   const compactForm=form;
   while(form&&form!==document.body&&!form.querySelector('[role=radio]'))form=form.parentElement;
   if(form===document.body)form=compactForm;
   if(form&&form!==document.body)roots.push(form);
   for(const input of document.querySelectorAll('input[aria-expanded="true"]')){
     if(!visible(input))continue;
     let popup=input.parentElement;
     while(popup&&popup!==document.body&&!popup.querySelector('[role=listitem],[role=option],[role=listbox]'))popup=popup.parentElement;
     if(popup&&popup!==document.body)roots.push(popup);
   }
 }
 if(scope&&scope.startsWith('card:')){
   const card=document.querySelector('[data-jb-card="'+scope.slice(5)+'"]');if(card)roots.push(card);
   roots.push(...[...document.querySelectorAll('[role=dialog]')].filter(visible));
 }
 if(scope==='sort')roots.push(...[...document.querySelectorAll('[role=tablist]')].filter(e=>visible(e)&&e.innerText.includes('Cheapest')));
 if(scope==='calendar')roots.push(...[...document.querySelectorAll('[aria-label*="Select the start date"],[aria-label="Go to next month"],[aria-label="Go to previous month"]')].filter(visible));
 for (const e of candidates) {
   if(scope&&!roots.some(r=>r.contains(e)))continue;
   if(!visible(e)||e.disabled||e.getAttribute('aria-disabled')==='true')continue;
   const tag=e.tagName.toLowerCase(), type=e.type||'';
   if(type==='password')continue;
   const id='n'+(++seq); e.setAttribute('data-jb-node',id);
   let role=e.getAttribute('role')||({button:'button',input: type==='checkbox'?'checkbox':type==='radio'?'radio':'textbox',textarea:'textbox',select:'combobox',a:'link'}[tag]||'button');
   const labelled=(e.getAttribute('aria-labelledby')||'').split(' ').map(x=>document.getElementById(x)?.textContent||'').join(' ');
   const domLabel=clean(e.getAttribute('aria-label')||labelled||[...e.labels||[]].map(x=>x.textContent).join(' ')||e.getAttribute('placeholder')||e.getAttribute('title')||e.innerText||e.getAttribute('name')||'');
   let label=domLabel;
   if(label==='Remove'){
     let p=e.parentElement;while(p&&p!==document.body&&!clean(p.innerText))p=p.parentElement;
     const chip=clean(p?.innerText).slice(0,70);
     let field=e.parentElement;while(field&&field!==document.body&&!field.querySelector('input[role=combobox]'))field=field.parentElement;
     const name=field&&field!==document.body?field.querySelector('input[role=combobox]').getAttribute('aria-label'):'';
     label='Remove '+chip+(name?' from '+name:'');
   }
   const context=clean(e.parentElement?.innerText).slice(0,220);
   const raw=e.value||'', display=role==='combobox'&&e.getAttribute('aria-expanded')==='false'?context:'';
   let field=e.matches('input[role=combobox]')?e:e.parentElement;
   while(field&&field!==document.body&&!field.matches('input[role=combobox]')&&field.querySelectorAll('input[role=combobox]').length!==1)field=field.parentElement;
   const fieldInput=field&&field!==document.body?(field.matches('input[role=combobox]')?field:field.querySelector('input[role=combobox]')):null;
   const fieldLabel=fieldInput?.getAttribute('aria-label')||null;
   const base={node:id,label:label.slice(0,180)||context.slice(0,90),dom_label:domLabel,field_label:fieldLabel,role,context,tag,type,value:raw||display,raw_value:raw,card_fingerprint:(__CARD_FINGERPRINT__)(e),value_source:raw?'input':display?'visible_selected_label':'empty',checked:typeof e.checked==='boolean'?e.checked:e.getAttribute('aria-checked'),selected:e.getAttribute('aria-selected'),expanded:e.getAttribute('aria-expanded'),placeholder:e.getAttribute('placeholder')||'',readonly:!!e.readOnly,href:e.href||null,observed_via:native.includes(e)?'semantic_dom':'visible_pointer_affordance'};
   if(tag==='input'||tag==='textarea'||e.isContentEditable){
     if(!e.readOnly&&!display&&!['checkbox','radio','submit','button','file'].includes(type))out.push({...base,id:id+'_fill',kind:'fill'});
   }
   if(tag==='select'){
     for(const o of e.options)if(!o.disabled)out.push({...base,id:id+'_s'+o.index,kind:'select',label:label+' → '+clean(o.textContent),value:o.value,current_value:e.value});
   }else out.push({...base,id:id+'_click',kind:'click'});
   if(seq>=180)break;
 }
 return {actions:out,scope_text:scope?roots.map(r=>r.innerText).join('\n'):null,scope_ready:!scope||roots.length>0};
}""".replace('__CARD_FINGERPRINT__', CARD_FINGERPRINT_JS)


class StaleObservation(RuntimeError):
    pass


class BrowserClosedError(RuntimeError):
    pass


def target_closed(error):
    return isinstance(error, PlaywrightError) and ('closed' in str(error).casefold() or 'disconnected' in str(error).casefold())


@dataclass
class Observation:
    id: str
    page_id: str
    url: str
    data: dict
    text: str


class Browser:
    def __init__(self, profile_dir=None, headless=False, extra_args=None):
        self.profile_dir = Path(profile_dir) if profile_dir else ROOT / 'profile'
        self.headless = headless
        self.extra_args = list(extra_args or [])
        self.pw = None
        self.context = None
        self.page = None
        self.page_ids = {}
        self.last = None
        self.presentation = False

    async def set_presentation(self, enabled):
        self.presentation = enabled
        if enabled:
            await self.start()
        if self.is_open():
            from .presentation import desktop_layout, window_bounds
            if enabled:
                bounds = desktop_layout()['site']
                await self.page.set_viewport_size({'width': max(800, bounds['width'] - 16), 'height': max(500, bounds['height'] - 112)})
                await window_bounds(self.context, self.page, bounds)
            else:
                await self.page.set_viewport_size({'width': 1440, 'height': 1000})
                bounds = desktop_layout()['site']
                await window_bounds(self.context, self.page, {'left': bounds['left'], 'top': bounds['top'],
                                                              'width': 1456, 'height': 1112})

    def is_open(self):
        if self.context is None or self.page is None or self.page.is_closed():
            return False
        browser = self.context.browser
        return browser is None or browser.is_connected()

    def _forget_page(self):
        self.page = None
        self.last = None
        self.page_ids.clear()

    def _context_closed(self, context):
        if self.context is context:
            self.context = None
            self._forget_page()

    def _page_closed(self, page):
        if self.page is page:
            self._forget_page()

    def _adopt_page(self, page):
        self.page = page
        self.last = None
        page.once('close', lambda *_: self._page_closed(page))

    async def start(self, video_dir: Path | None = None):
        if self.is_open():
            return
        if self.context is not None:
            context = self.context
            browser = context.browser
            if browser is None or browser.is_connected():
                try:
                    pages = [page for page in context.pages if not page.is_closed()]
                    self._adopt_page(pages[-1] if pages else await context.new_page())
                    return
                except PlaywrightError as error:
                    if not target_closed(error):
                        raise
        # A non-null Python object does not imply a live browser connection.
        # Dispose the old transport before reusing this persistent profile.
        await self.close()
        self.pw = await async_playwright().start()
        options = dict(headless=self.headless, viewport={'width': 1440, 'height': 1000}, env=desktop_env(), locale='en-US', timezone_id='Asia/Shanghai', accept_downloads=False, args=['--no-first-run', '--disable-dev-shm-usage', '--window-position=0,0'] + self.extra_args)
        if self.headless:
            options['executable_path'] = self.pw.chromium.executable_path
        if video_dir:
            video_dir.mkdir(parents=True, exist_ok=True)
            options['record_video_dir'] = str(video_dir)
        self.context = await self.pw.chromium.launch_persistent_context(str(self.profile_dir), **options)
        self.context.set_default_timeout(10000)
        context = self.context
        context.once('close', lambda *_: self._context_closed(context))
        self._adopt_page(context.pages[0] if context.pages else await context.new_page())
        if self.presentation:
            await self.set_presentation(True)

    async def navigate(self, url):
        # Only startup navigation is safe to retry. Never replay task actions.
        for attempt in range(2):
            await self.start()
            page = self.page
            try:
                await page.goto(url, wait_until='domcontentloaded', timeout=45000)
                await page.bring_to_front()
                return
            except PlaywrightError as error:
                if not target_closed(error):
                    raise
                await self.close()
                if attempt:
                    raise BrowserClosedError('Browser closed twice during startup; task stopped. Submit a new task to try again.') from error

    def page_id(self):
        if not self.is_open():
            raise BrowserClosedError('Browser is closed; task stopped. Submit a new task to reopen it.')
        return self.page_ids.setdefault(self.page, uuid.uuid4().hex)

    async def observe(self, scope=None):
        if not self.is_open():
            raise BrowserClosedError('Browser is closed; task stopped. Submit a new task to reopen it.')
        if scope == 'calendar':
            await self.page.locator('[aria-label*="Select the start date"]').first.wait_for(timeout=15000)
        text = await self.page.locator('body').inner_text(timeout=15000)
        observed = await self.page.evaluate(CONTROLS_JS, scope)
        if scope == 'flight_form' and not observed['scope_ready']:
            await self.page.wait_for_function("()=>!!document.querySelector('input[aria-label=\"Departure airport or city\"]')&&[...document.querySelectorAll('button,[role=button],[data-testid]')].some(e=>(e.getAttribute('aria-label')||e.getAttribute('title')||e.innerText||'').trim()==='Search')", timeout=15000)
            observed = await self.page.evaluate(CONTROLS_JS, scope)
            text = await self.page.locator('body').inner_text()
        controls = observed['actions']
        data = {'url': self.page.url, 'title': await self.page.title(), 'text': (observed['scope_text'] if scope else text)[:12000], 'observation_scope': scope or 'page', 'scope_ready': observed['scope_ready'], 'actions': controls + [
            {'id': 'press_enter', 'kind': 'key', 'label': 'Press Enter'},
            {'id': 'scroll_down', 'kind': 'scroll', 'label': 'Scroll down'},
            {'id': 'scroll_up', 'kind': 'scroll', 'label': 'Scroll up'},
            {'id': 'wait', 'kind': 'wait', 'label': 'Wait for submitted results or an absent control to load'},
        ], 'frames': [f.url for f in self.page.frames if f != self.page.main_frame]}
        self.last = Observation(uuid.uuid4().hex, self.page_id(), self.page.url, data, text)
        return self.last

    async def execute(self, observation_id, page_id, action, text=None, operation=None, actor="browser_executor"):
        operation = operation or (lambda *args, **kwargs: nullcontext())
        with operation('validate', 'executor_guard', 'Validate the observed action', action=action):
            obs = self.last
            if obs and (obs.id != observation_id or obs.page_id != page_id):
                raise StaleObservation('Page/observation changed; observe again')
            if not self.is_open():
                raise BrowserClosedError('Browser was closed during the task; no action was replayed. Submit a new task to reopen it.')
            if not obs or obs.id != observation_id or obs.page_id != page_id or self.page_id() != page_id or self.page.url != obs.url:
                raise StaleObservation('Page/observation changed; observe again')
            if not any(a['id'] == action['id'] and a == action for a in obs.data['actions']):
                raise StaleObservation('Action is not in current candidates')
            before_text = (await self.page.locator('body').inner_text())[:10000]
            before_url = self.page.url
            before_pages = set(self.context.pages)
            before_scroll = await self.page.evaluate('()=>[scrollX,scrollY]')
            kind = action['kind']
            started = time.perf_counter()
            validation_started = started
            state_before = None
            if kind in ('click', 'fill', 'select'):
                target = self.page.locator(f'[data-jb-node="{action["node"]}"]')
                if await target.count() != 1 or not await target.is_visible() or not await target.is_enabled():
                    raise StaleObservation('Observed target disappeared or became disabled')
                current = await target.evaluate(r'''e=>{const clean=s=>(s||'').replace(/\s+/g,' ').trim();const labelled=(e.getAttribute('aria-labelledby')||'').split(' ').map(x=>document.getElementById(x)?.textContent||'').join(' ');const label=clean(e.getAttribute('aria-label')||labelled||[...e.labels||[]].map(x=>x.textContent).join(' ')||e.getAttribute('placeholder')||e.getAttribute('title')||e.innerText||e.getAttribute('name')||'');const context=clean(e.parentElement?.innerText).slice(0,220);return {label:label.slice(0,180)||context.slice(0,90),raw_value:e.value||'',expanded:e.getAttribute('aria-expanded')};}''')
                expected_label = action.get('dom_label', action['label'].split(' → ')[0] if kind == 'select' else action['label'])
                if current['label'] != expected_label or current['expanded'] != action.get('expanded'):
                    raise StaleObservation('Target meaning/state changed; observe again')
                if kind == 'fill' and current['raw_value'] != action.get('raw_value', action.get('value', '')):
                    raise StaleObservation('Field value changed; observe again')
                state_before = await target.evaluate(STATE_JS)
                if action.get('card_fingerprint') is not None and state_before['card_fingerprint'] != action['card_fingerprint']:
                    raise StaleObservation('Flight identity or price changed; observe again')
            validation_seconds = time.perf_counter() - validation_started
        with operation('execute', actor, ('Type: ' if text is not None else 'Action: ') + action['label'], action=action):
            execution_started = time.perf_counter()
            if kind == 'fill':
                if text is None:
                    raise ValueError('Missing field text')
                await target.fill(text)
            elif kind == 'select':
                await target.select_option(action['value'])
            elif kind == 'click':
                await target.click()
            elif kind == 'key':
                await self.page.keyboard.press('Enter')
            elif kind == 'scroll':
                await self.page.mouse.wheel(0, -650 if 'up' in action['id'] else 650)
            elif kind != 'wait':
                raise ValueError(f'Unsupported action: {kind}')
            execution_seconds = time.perf_counter() - execution_started
        with operation('wait', 'website_wait', 'Wait for the action postcondition', action=action):
            wait_started = time.perf_counter()
            old = {'url': before_url, 'text': before_text, 'node': action.get('node'), 'state': state_before, 'scroll': before_scroll}
            progress_reason, timed_out = 'timeout', False
            try:
                handle = await self.page.wait_for_function(PROGRESS_JS, arg=old, timeout=4000 if kind != 'wait' else 8000)
                progress_reason = await handle.json_value()
                await handle.dispose()
            except PlaywrightTimeout:
                timed_out = True
            new = [p for p in self.context.pages if p not in before_pages]
            if new:
                self._adopt_page(new[-1])
                await self.page.wait_for_load_state('domcontentloaded', timeout=30000)
                await self.page.bring_to_front()
            elif self.page.url != before_url:
                await self.page.wait_for_load_state('domcontentloaded', timeout=30000)
            changed = bool(new) or self.page.url != before_url or bool(await self.page.evaluate(PROGRESS_JS, old))
        return {'action': action['label'], 'kind': kind, 'text': text, 'page_changed': changed, 'new_page': bool(new),
                'seconds': time.perf_counter() - started, 'validation_seconds': validation_seconds,
                'execution_seconds': execution_seconds, 'postcondition_wait_seconds': time.perf_counter() - wait_started,
                'progress_reason': 'new_page' if new else progress_reason, 'wait_timed_out': timed_out}

    async def screenshot(self, path):
        session = await self.context.new_cdp_session(self.page)
        try:
            result = await asyncio.wait_for(session.send('Page.captureScreenshot', {'format': 'png', 'captureBeyondViewport': False}), timeout=10)
            Path(path).write_bytes(base64.b64decode(result['data']))
        finally:
            try:
                await asyncio.wait_for(session.detach(), timeout=2)
            except (PlaywrightError, asyncio.TimeoutError):
                pass

    async def close(self):
        context, pw = self.context, self.pw
        self.context = None
        self.pw = None
        self._forget_page()
        try:
            if context is not None:
                try:
                    await context.close()
                except PlaywrightError as error:
                    if not target_closed(error):
                        raise
        finally:
            if pw is not None:
                try:
                    await pw.stop()
                except PlaywrightError as error:
                    if not target_closed(error):
                        raise
