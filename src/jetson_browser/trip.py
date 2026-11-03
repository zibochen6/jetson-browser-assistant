"""Trip.com observations, control-specific date adapter, and independent checks."""
from datetime import datetime
import asyncio
import re
import time
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo
from types import SimpleNamespace

from .locations import location, normalized
from .browser import CARD_FINGERPRINT_JS, StaleObservation


class Blocked(RuntimeError):
    pass


def checked(value):
    return value is True or value == 'true'


def date_matches(day, text):
    if day.isoformat() in text:
        return True
    month = day.strftime('%b')
    return bool(re.search(r'\b' + month + r'[a-z]*\s+0?' + str(day.day) + r'\b', text, re.I))


def nonstop_status(summary, text):
    if re.search(r'layover|self[- ]transfer|connecting flight|\b[12]\s+stops?\b|转机', summary + '\n' + text, re.I):
        return False
    return True if re.search(r'nonstop|non-stop|直飞', summary, re.I) else None


class Trip:
    def __init__(self, task):
        self.task = task
        self.origin = location(task.origin)
        self.destination = location(task.destination)
        self.date_proof = None
        self.query_proof = None
        self.sort_proof = None

    def form_checks(self, observation):
        actions = observation.data['actions']
        def field(part):
            return next((a for a in actions if a.get('role') == 'combobox' and part in a['label']), {})
        origin, destination = field('Departure airport or city'), field('Arrival airport or city')
        date = next((a for a in actions if a['kind'] == 'click' and a.get('role') == 'textbox' and 'date' in a['label'].lower()), {})
        one_way = next((a for a in actions if a['label'] == 'One-way' and a.get('role') == 'radio'), {})
        nonstop = next((a for a in actions if a['label'] == 'Nonstop' and a.get('role') == 'checkbox'), {})
        passenger = next((a for a in actions if re.search(r'\badult', a['label'], re.I) and 'economy' in a['label'].lower()), {})
        checks = {
            'origin': self.origin.matches_selected(origin.get('value', '')) and origin.get('expanded') == 'false',
            'destination': self.destination.matches_selected(destination.get('value', '')) and destination.get('expanded') == 'false',
            'one_way': checked(one_way.get('checked')),
            'date': bool(self.date_proof and date_matches(self.task.departure_date, date.get('value', ''))),
            'passengers_cabin': bool(re.search(r'\b' + str(self.task.adults) + r'\s+adult', passenger.get('label', ''), re.I)),
            'nonstop_filter': bool(nonstop) and checked(nonstop.get('checked')) == self.task.direct_only,
        }
        return checks, {'origin': origin, 'destination': destination, 'date': date,
                        'one_way': one_way, 'nonstop': nonstop, 'passengers_cabin': passenger}

    def form_goal(self, checks):
        requirements = {
            'origin': f'departure {self.origin.query}, ' + ('ALL AIRPORTS' if self.origin.kind == 'city' else 'specific airport'),
            'destination': f'arrival {self.destination.query}, ' + ('ALL AIRPORTS' if self.destination.kind == 'city' else 'specific airport'),
            'one_way': 'One-way selected',
            'date': 'departure date ' + self.task.departure_date.strftime('%A, %B ') + str(self.task.departure_date.day) + self.task.departure_date.strftime(', %Y') + ' using the date picker',
            'passengers_cabin': f'{self.task.adults} adult, Economy',
            'nonstop_filter': 'Nonstop checkbox ' + ('ON' if self.task.direct_only else 'OFF; direct flights are a preference only'),
        }
        missing = [value for key, value in requirements.items() if not checks[key]]
        if not missing:
            return 'The flight query is configured and independently verified. CLICK Search to load real flight results. Do not finish on the form.'
        city_instructions = (' Replace incorrect existing city selections: remove the incorrect chips before typing, do not add a second city. Select a matching autocomplete suggestion after typing a city.'
                             if not checks['origin'] or not checks['destination'] else '')
        return 'Configure this flight search. Current stage: set ' + missing[0] + '. Complete this stage before changing other fields. Preserve satisfied fields.' + city_instructions + ' Submit only when every condition is set.'

    def allowed_form_actions(self, observation, checks):
        """Preserve verified conditions; type/category preconditions use current DOM data."""
        actions = observation.data['actions']
        stage = 'Departure airport or city' if not checks['origin'] else 'Arrival airport or city' if not checks['destination'] else None
        selected_chips = any(a.get('field_label') == stage and a.get('dom_label') == 'Remove' for a in actions) if stage else False
        place = self.origin if stage == 'Departure airport or city' else self.destination
        allowed, excluded = [], []
        for action in actions:
            label, role, field = action['label'], action.get('role'), action.get('field_label')
            valid = action['kind'] != 'key'
            if stage:
                valid &= field == stage
                if selected_chips:
                    valid &= action.get('dom_label') == 'Remove'
                elif role == 'listitem' and place.kind == 'city':
                    valid = False  # Airport rows cannot satisfy an all-airports city request.
                elif role == 'button' and action.get('dom_label') != 'Remove':
                    valid &= ('All airports' in label) if place.kind == 'city' else ('All airports' not in label)
            else:
                # Editing a verified field or swapping the route would undo evidence.
                valid &= field is None and not label.startswith('Switch departure')
                if role == 'radio' and checks['one_way']:
                    valid = False
                if role == 'checkbox' and label == 'Nonstop' and checks['nonstop_filter']:
                    valid = False
                if role == 'textbox' and 'date' in label.lower() and (checks['date'] or not checks['one_way']):
                    valid = False
                if re.search(r'\badult', label, re.I) and 'economy' in label.lower() and checks['passengers_cabin']:
                    valid = False
                if label == 'Search' and not all(checks.values()):
                    valid = False
            (allowed if valid else excluded).append(action)
        return allowed, {'current_city_stage': stage, 'selected_chips_must_be_cleared': selected_chips,
                         'excluded_by_preconditions': [a['id'] for a in excluded]}

    def form_ready(self, observation, checks, actions):
        if not actions:
            return False
        label = 'Departure airport or city' if not checks['origin'] else 'Arrival airport or city' if not checks['destination'] else None
        if label is None:
            return True
        place = self.origin if label.startswith('Departure') else self.destination
        typed = any(a.get('field_label') == label and a.get('role') == 'combobox' and a.get('expanded') == 'true'
                    and normalized(a.get('raw_value', '')) == normalized(place.query) for a in actions)
        if not typed:
            return True
        # Wait for an actual matching option, rather than deciding while the
        # city popup is still mounting or displaying an old suggestion list.
        return any(a['kind'] == 'click' and a.get('role') in ['button', 'listitem', 'option']
                   and normalized(place.query) in normalized(a['label']) and a.get('dom_label') != 'Remove'
                   for a in actions)

    async def select_date(self, context):
        context.trace.adapter('calendar')
        target = self.task.departure_date
        prefix = target.strftime('%A, %B ') + str(target.day) + target.strftime(', %Y')
        stale_retries = 0
        for _ in range(14):
            obs = await context.observe(scope='calendar')
            dates = [a for a in obs.data['actions'] if a['kind'] == 'click' and a['label'].startswith(prefix) and 'Select the start date' in a['label']]
            if len(dates) == 1:
                try:
                    await context.execute(obs, dates[0], actor='site_adapter', note='Select the observed full calendar date')
                except StaleObservation:
                    stale_retries += 1
                    if stale_retries > 2:
                        raise Blocked('Calendar kept changing; stale-target retry limit reached')
                    continue
                self.date_proof = {'requested': target.isoformat(), 'observed_calendar_label': dates[0]['label'],
                                   'observation_id': obs.id, 'page_id': obs.page_id}
                after = await context.observe(scope='flight_form')
                date_fields = [a for a in after.data['actions'] if a.get('role') == 'textbox' and a['kind'] == 'click' and 'date' in a['label'].lower()]
                if any(date_matches(target, a.get('value', '')) for a in date_fields):
                    self.date_proof['readback'] = date_fields
                    context.trace.event('verifier', f'Departure date verified: {target.isoformat()}', proof=self.date_proof)
                    return
                raise Blocked('Date readback does not match the requested date; stopped')
            next_buttons = [a for a in obs.data['actions'] if a['kind'] == 'click' and a['label'] == 'Go to next month']
            if len(next_buttons) != 1:
                raise Blocked('The calendar has no observable target date or next-month button')
            await context.execute(obs, next_buttons[0], actor='site_adapter', note='Go to the next calendar month')
        raise Blocked('The requested date exceeds the calendar range supported by this run')

    @staticmethod
    async def user_intervention(page, text):
        if await page.locator('input[type="password"]:visible').count():
            return 'The website requires login; sign in manually in the device browser'
        if re.search(r'verify (?:that )?you are (?:a )?human|security verification|complete the captcha|验证码|安全验证', text, re.I):
            return 'The website requires human verification; complete it in the browser before resuming'
        for frame in page.frames:
            if re.search(r'recaptcha|hcaptcha|captcha', frame.url, re.I):
                element = await frame.frame_element() if frame != page.main_frame else None
                if element is not None and await element.is_visible():
                    return 'A CAPTCHA is visible; complete it manually before resuming'
        return None

    @staticmethod
    def transaction_guard(action):
        if re.search(r'pay now|confirm (?:booking|order)|submit order|purchase|book now|^book$|立即支付|提交订单|确认预订', action['label'], re.I):
            raise Blocked('This action may submit a transaction and is outside search and viewing permissions')

    def verify_result_query(self, observation):
        query = parse_qs(urlparse(observation.url).query)
        body = observation.text
        date_ok = query.get('ddate') == [self.task.departure_date.isoformat()]
        query_ok = query.get('triptype') == ['ow'] and query.get('quantity') == [str(self.task.adults)] and query.get('class') == ['y']
        passengers = bool(re.search(r'\b' + str(self.task.adults) + r'\s+adult', body, re.I))
        cabin = 'economy' in body.lower()
        return bool(self.query_proof and all(self.query_proof['checks'].values()) and date_ok and query_ok and passengers and cabin)

    @staticmethod
    async def sort_selected(page):
        return await page.evaluate(r'''()=>{const e=[...document.querySelectorAll('[role=tab]')].find(e=>e.getAttribute('aria-label')==='Cheapest'&&e.getAttribute('aria-selected')==='true');return e?{text:e.innerText,ariaSelected:e.getAttribute('aria-selected'),label:e.getAttribute('aria-label')}:null;}''')

    async def fare_options(self, page, selected):
        # The fare list and itinerary header arrive separately on the real site.
        # Wait for independently matching content rather than weakening the proof.
        started = time.monotonic()
        while True:
            proof = await self._fare_options_once(page, selected)
            if proof:
                proof['verification_wait_seconds'] = time.monotonic() - started
                return proof
            if time.monotonic() - started >= 12:
                return None
            await asyncio.sleep(.2)

    async def _fare_options_once(self, page, selected):
        popup = await page.evaluate(r'''()=>{
          const e=[...document.querySelectorAll('div,span,h2,h3')].find(e=>e.getBoundingClientRect().width>0&&e.textContent.trim()==='Select Fare');
          if(!e)return null;let root=e;while(root&&root!==document.body&&!root.querySelector('[aria-label="Close"]'))root=root.parentElement;
          return root&&root!==document.body?{text:root.innerText,role:root.getAttribute('role')}:null;
        }''')
        if not popup:
            return None
        route = normalized(self.origin.city) in normalized(popup['text']) and normalized(self.destination.city) in normalized(popup['text'])
        price = selected['price'] is not None and re.search(r'(?:US\$|USD|CNY|\$|¥)\s*' + re.escape(str(int(selected['price'])) if selected['price'].is_integer() else str(selected['price'])) + r'\b', popup['text'])
        same_times = selected['departure_time'] in popup['text'] and selected['arrival_time'] in popup['text']
        same_date = parse_qs(urlparse(page.url).query).get('ddate') == [selected['departure_date']]
        if route and price and same_times and same_date and 'Cancellation fee' in popup['text'] and 'midpolicyid=' in page.url:
            return {'visible_popup': popup, 'url': page.url, 'selected_flight': selected,
                    'route_verified': True, 'times_verified': True, 'date_verified': True, 'candidate_price_present': True}
        return None

    async def matches_card(self, page, selected):
        current = await page.evaluate(r'''id=>{const e=document.querySelector('[data-jb-card="'+id+'"]');return e?(__CARD_FINGERPRINT__)(e):null;}'''.replace('__CARD_FINGERPRINT__', CARD_FINGERPRINT_JS), selected['card_id'])
        return current is not None and current == selected.get('card_fingerprint')

    async def wait_for_results(self, page, timeout=60, tick=None, progress=None):
        """Wait for verified, complete and stable cards, not a global spinner."""
        deadline = time.monotonic() + timeout
        last_signature, stable_since = None, None
        negative = False
        next_notice = time.monotonic() + 5
        while time.monotonic() < deadline:
            if tick:
                tick()
            body = await page.locator('body').inner_text()
            intervention = await self.user_intervention(page, body)
            if intervention:
                return {'kind': 'needs_user', 'message': intervention}
            if 'access denied' in body.casefold():
                raise Blocked('The website denied access; execution stopped')
            if self.verify_result_query(SimpleNamespace(url=page.url, text=body)):
                negative = bool(re.search(r'no flights found|no matching flights|no results found|没有符合|暂无航班', body, re.I))
                cards = await self.cards(page)
                complete = [f for f in cards if f['route_verified'] and f.get('departure_date') == self.task.departure_date.isoformat()
                            and all(f.get(k) is not None for k in ['departure_time', 'arrival_time', 'arrival_date', 'price', 'currency'])]
                signature = tuple(f['card_fingerprint'] for f in complete)
                now = time.monotonic()
                if signature and signature == last_signature:
                    if now - stable_since >= .5:
                        return {'kind': 'ready', 'cards': complete}
                else:
                    last_signature, stable_since = signature, now
            else:
                last_signature, stable_since = None, None
                negative = False
            if progress and time.monotonic() >= next_notice:
                progress()
                next_notice = time.monotonic() + 5
            await asyncio.sleep(.25)
        if negative:
            return {'kind': 'no_results'}
        raise Blocked('Timed out waiting for complete, stable flight results matching the submitted query')

    async def cards(self, page):
        raw = await page.evaluate(r'''()=>{
          const visible=e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0&&getComputedStyle(e).visibility!=='hidden';};
          const minimal=[...document.querySelectorAll('[data-testid^="u-flight-card-"]')].filter(e=>visible(e)&&e.querySelector('[aria-label^="Flight departing from"]')).slice(0,20);
          for(const old of document.querySelectorAll('[data-jb-card]'))old.removeAttribute('data-jb-card');
          return minimal.map((e,i)=>{e.setAttribute('data-jb-card','c'+i);return {id:'c'+i,fingerprint:(__CARD_FINGERPRINT__)(e),text:e.innerText,classes:e.className,route_aria:[...e.querySelectorAll('[aria-label^="Flight departing from"]')].map(x=>x.getAttribute('aria-label')).join('\n'),price_aria:e.querySelector('[aria-label^="One-way price:"]')?.getAttribute('aria-label')||'',airline_names:[...e.querySelectorAll('[data-testid="flights-name"]')].filter(visible).map(x=>x.innerText),airline_alt:[...e.querySelectorAll('img[alt]')].filter(visible).map(x=>x.alt),links:[...e.querySelectorAll('a[href]')].filter(visible).map(x=>({text:x.innerText,href:x.href}))};});
        }'''.replace('__CARD_FINGERPRINT__', CARD_FINGERPRINT_JS))
        body = await page.locator('body').inner_text()
        header_currency = None
        for code in ['USD', 'CNY', 'EUR', 'GBP', 'SGD', 'HKD', 'JPY', 'AUD', 'CAD']:
            if re.search(r'\b' + code + r'\b', body[:1000]):
                header_currency = code
                break
        cards = []
        for row in raw:
            text = row['text']
            times = re.findall(r'\b\d{1,2}:\d{2}\b', text)
            codes = list(dict.fromkeys(code for code in re.findall(r'\b[A-Z]{3}\b', text) if code not in ['USD', 'CNY', 'EUR', 'GBP', 'SGD', 'HKD', 'JPY', 'AUD', 'CAD', 'VIP']))
            prices = re.findall(r'(US\$|USD|CNY|EUR|GBP|SGD|HKD|\$|¥|€|£)\s*([\d,]+(?:\.\d{1,2})?)', row['price_aria'])
            currency, price = None, None
            if prices:
                symbol, amount = prices[-1]
                currency = {'US$': 'USD', '€': 'EUR', '£': 'GBP', '$': header_currency, '¥': header_currency}.get(symbol, symbol)
                price = float(amount.replace(',', ''))
            airline = ' / '.join(row['airline_names']) or next((v for v in row['airline_alt'] if re.search(r'air|航空', v, re.I)), None)
            if not airline:
                airline = next((line.strip() for line in text.splitlines() if re.search(r'airlines|airways|\bair\b|航空', line, re.I) and len(line.strip()) < 90), None)
            number = re.search(r'\b(?:[A-Z][A-Z0-9]|[0-9][A-Z])\s?\d{3,4}\b', text)
            nonstop = nonstop_status(row['route_aria'], text)
            note = 'Starting price' if re.search(r'\bfrom\b|起', text, re.I) else None
            flight = {'airline': airline, 'flight_number': number[0] if number else None,
                      'departure_airport': codes[0] if codes else None, 'arrival_airport': codes[-1] if len(codes) > 1 else None,
                      'departure_time': times[0] if times else None, 'arrival_time': times[-1] if len(times) > 1 else None,
                      'nonstop': nonstop, 'price': price, 'currency': currency,
                      'price_note': note or 'Price basis and optional extras: see website terms',
                      'link': row['links'][0]['href'] if row['links'] else page.url,
                      'collected_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
                      'card_id': row['id'], 'card_fingerprint': row['fingerprint'], 'source_text': text, 'source_classes': row['classes']}
            routes = re.findall(r'Flight departing from (.+?) at (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) and arriving at (.+?) at (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', row['route_aria'])
            flight['accessible_summary'] = row['route_aria']
            if routes:
                first, last = routes[0], routes[-1]
                flight.update(departure_airport=(codes[0] + ' ' if codes else '') + first[0],
                              arrival_airport=(codes[-1] + ' ' if len(codes)>1 else '') + last[2],
                              departure_time=first[1][11:16], arrival_time=last[3][11:16],
                              departure_date=first[1][:10], arrival_date=last[3][:10])
                if len(routes) > 1:
                    flight['nonstop'] = False
            flight['route_verified'] = bool(flight['departure_airport'] and flight['arrival_airport'] and self.origin.matches_airport(flight['departure_airport']) and self.destination.matches_airport(flight['arrival_airport']))
            cards.append(flight)
        return cards

    def eligible(self, cards):
        candidates = [f for f in cards if f['route_verified'] and f.get('departure_date') == self.task.departure_date.isoformat() and (not self.task.direct_only or f['nonstop'] is True)]
        if self.task.budget is not None:
            candidates = [f for f in candidates if f['currency'] == self.task.currency and f['price'] is not None and f['price'] <= self.task.budget]
        if self.task.direct_preferred:
            candidates.sort(key=lambda f: (f['nonstop'] is not True, f['price'] if f['price'] is not None else float('inf')))
        elif self.task.price_preferred:
            candidates.sort(key=lambda f: f['price'] if f['price'] is not None else float('inf'))
        return candidates[:3]
