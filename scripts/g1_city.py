"""G1: GPU Laya chooses actions on a real site; city text is a supplied test input.

This isolated test does not claim Qwen integration or complete flight-query success.
"""
import asyncio
from datetime import datetime
import json
import time
from zoneinfo import ZoneInfo

from jetson_browser.browser import Browser, StaleObservation
from jetson_browser.config import ROOT, settings
from jetson_browser.llm import laya_decide
from jetson_browser.locations import location


async def case(browser, city, run):
    run.mkdir()
    goal = (f'Set the DEPARTURE city to {city}, ALL AIRPORTS. Choose the actual matching city autocomplete suggestion. '
            'Leave destination and dates unchanged. Do not search or book flights. '
            'Finish only after the departure city is committed and the suggestion popup is closed.')
    (run / 'task.json').write_text(json.dumps({'goal': goal, 'city': city, 'site': 'trip',
        'text_source': 'literal city from test input; no Qwen generation in this isolated test'}, indent=2))
    history, selection = [], None
    t = time.perf_counter()
    no_progress, stale_retries = 0, 0
    success, error = False, None
    with (run / 'events.jsonl').open('a', buffering=1) as log:
        def event(actor, **data):
            log.write(json.dumps({'actor': actor, 'timestamp': time.time(), **data}, ensure_ascii=False) + '\n')
        try:
            await browser.navigate(settings()['entry_url'])
            await browser.page.locator('input[aria-label="Departure airport or city"]').first.wait_for(timeout=45000)
            event('site_observer', operation='wait_for_flight_form_and_scope_to_form_and_popup')
            for step in range(12):
                observation = await browser.observe(scope='flight_form')
                current = [a for a in observation.data['actions'] if a.get('field_label') == 'Departure airport or city']
                has_chips = any(a.get('dom_label') == 'Remove' for a in current)
                observation.data['actions'] = [a for a in current if not has_chips or a.get('dom_label') == 'Remove']
                (run / f'observation-{step:02d}.json').write_text(json.dumps(observation.data, ensure_ascii=False, indent=2))
                decision = await laya_decide(observation.data, goal, history)
                event('laya', observation_id=observation.id, page_id=observation.page_id, decision=decision)
                action = decision.get('action')
                print(city, step, decision['operation'], action and action['label'], decision['latency_ms'], flush=True)
                if decision['operation'] in ['DONE', 'BLOCKED']:
                    error = 'model stopped before independent verification'
                    break
                if not action:
                    error = 'no executable action'
                    break
                value = None
                if action['kind'] == 'fill':
                    if 'Departure' not in action['label']:
                        error = 'model selected a field outside departure-city scope'
                        break
                    value = city
                if action['kind'] == 'click':
                    allowed = action.get('role') != 'link' and ('Departure' in action['label'] or city.lower() in action['label'].lower() or action['label'].lower() in ['accept', 'accept all', 'reject all', 'close'])
                    if not allowed:
                        error = f'model selected unrelated control: {action["label"]}'
                        break
                try:
                    result = await browser.execute(observation.id, observation.page_id, action, value)
                except StaleObservation as e:
                    stale_retries += 1
                    event('executor_guard', error=str(e), retry=stale_retries)
                    if stale_retries > 2:
                        raise
                    continue
                history.append(result)
                event('browser_executor', action=action, result=result)
                if value:
                    try:
                        await browser.page.wait_for_function("city=>[...document.querySelectorAll('[role=button]')].some(e=>e.innerText.toLowerCase().includes(city.toLowerCase())&&e.innerText.includes('All airports'))", arg=city, timeout=10000)
                        event('site_observer', operation='wait_for_city_suggestions', city=city)
                    except Exception as e:
                        event('site_observer', waiting_error=str(e))
                if action['kind'] == 'click' and action.get('dom_label') != 'Remove' and city.lower() in action['label'].lower() and 'All airports' in action['label']:
                    selection = {'observed_option': action, 'observation_id': observation.id}
                after = await browser.observe(scope='flight_form')
                inputs = list({a['node']:a for a in after.data['actions'] if a.get('role') == 'combobox' and 'Departure' in a['label']}.values())
                committed = [a for a in inputs if location(city).matches_selected(a['value']) and a['expanded'] in [False, 'false']]
                if selection and len(committed) == 1:
                    success = True
                    selection['readback'] = committed[0]
                    break
                no_progress = 0 if result['page_changed'] else no_progress + 1
                if no_progress >= 3:
                    error = 'three actions without progress'
                    break
        except Exception as e:
            error = f'{type(e).__name__}: {e}'
            event('failure', error=error)
        finally:
            try:
                await browser.screenshot(run / 'final.png')
                state = await browser.observe()
                (run / 'final-page.json').write_text(json.dumps(state.data, ensure_ascii=False, indent=2))
            except Exception as e:
                event('artifact_error', error=str(e))
    result = {'city': city, 'success': success, 'selection': selection, 'error': error,
              'seconds': time.perf_counter() - t, 'actions': len(history), 'human_takeover': False,
              'site_adapter': 'Trip.com observation scope, readiness, departure-field action preconditions; no adapter clicks',
              'model': 'Laya v19s on Jetson CUDA'}
    (run / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


async def main():
    folder = ROOT / 'runs' / ('g1-' + datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d-%H%M%S'))
    folder.mkdir(parents=True)
    browser = Browser(profile_dir=folder / 'profile')
    results = []
    try:
        await browser.start(video_dir=folder / 'video')
        for city in ['Guangzhou', 'Shenzhen', 'Hangzhou', 'Xiamen', 'Singapore']:
            results.append(await case(browser, city, folder / city))
    finally:
        await browser.close()
        summary = {'passed': sum(r['success'] for r in results), 'total': len(results), 'results': results,
                   'threshold': 'at least 4/5', 'qwen_integration_tested': False, 'real_site': settings()['entry_url']}
        (folder / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
        (ROOT / 'evidence/g1-latest.json').write_text(json.dumps({'folder': str(folder), **summary}, ensure_ascii=False, indent=2))
        print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
