"""Critical independent-verifier invariants; drawing is accepted on the device."""
import copy
from types import SimpleNamespace

import pytest

from jetson_browser.whiteboard_scene import Change, Goal, candidates, compile_goal, remaining_goal, scene, validate_intent, verify


def rectangle(ident, label, x, y):
    return [dict(id=ident, type='rectangle', x=x, y=y, width=200, height=112, angle=0,
                 strokeColor='#1e1e1e', backgroundColor='transparent', boundElements=[{'type':'text','id':ident+'t'}]),
            dict(id=ident+'t',type='text',containerId=ident,text=label)]


def raw_scene():
    return {'elements': rectangle('a','Camera',350,320) + rectangle('b','Jetson',710,320) + [
        dict(id='edge',type='arrow',startBinding={'elementId':'a'},endBinding={'elementId':'b'},endArrowhead='arrow',strokeColor='#1e1e1e')],
        'appState':{'selectedElementIds':{}}}


def goal(*changes):
    return Goal(changes=[Change(op=c[0],target=c[1],text=c[2] if len(c)>2 else '',color='',position='',reference='') for c in changes],
                needs_clarification=False, clarification='')


def test_verifier_requires_actual_labels_colors_and_preserved_objects():
    before=raw_scene()
    contract=compile_goal(goal(),scene(before))
    assert verify(contract,scene(before))['passed']
    for changed in ('label','color','label_color','delete','replace_text_id'):
        after=copy.deepcopy(before)
        if changed=='label': after['elements'][1]['text']='Fake'
        elif changed=='color': after['elements'][2]['backgroundColor']='#b2f2bb'
        elif changed=='label_color': after['elements'][1]['strokeColor']='#e03131'
        elif changed=='delete': after['elements']=after['elements'][2:]
        else:
            after['elements'][1]['id']='replacement'
            after['elements'][0]['boundElements'][0]['id']='replacement'
        assert not verify(contract,scene(after))['passed'], changed


@pytest.mark.parametrize('change',['missing_binding','wrong_direction','replacement_id','extra_arrow','stroke'])
def test_arrow_identity_binding_direction_and_style_are_independent_requirements(change):
    before=raw_scene();contract=compile_goal(goal(),scene(before));after=copy.deepcopy(before)
    arrow=after['elements'][-1]
    if change=='missing_binding': arrow['endBinding']=None
    elif change=='wrong_direction': arrow['startBinding'],arrow['endBinding']=arrow['endBinding'],arrow['startBinding']
    elif change=='replacement_id': arrow['id']='new_edge'
    elif change=='extra_arrow': after['elements'].append(dict(arrow,id='extra'))
    else: arrow['strokeColor']='#e03131'
    assert not verify(contract,scene(after))['passed']


def test_external_move_is_read_from_fresh_scene_and_original_identity_is_retained():
    displaced=raw_scene();displaced['elements'][0].update(x=1060,y=680)
    g=Goal(changes=[Change(op='move',target='Camera',text='',color='',position='left',reference='Jetson')],needs_clarification=False,clarification='')
    contract=compile_goal(g,scene(displaced))
    assert not verify(contract,scene(displaced))['passed']
    move=next(a for a in candidates(contract,scene(displaced)) if a['op']=='move')
    assert move['target']=='a' and (move['x'],move['y'])==(350,320)
    restored=copy.deepcopy(displaced);restored['elements'][0].update(x=350,y=320)
    assert verify(contract,scene(restored))['passed']
    restored['elements'][0]['id']='new_camera'
    assert not verify(contract,scene(restored))['passed']


def test_color_candidates_include_real_alternatives_but_goal_does_not_request_them_all():
    before=raw_scene()
    g=Goal(changes=[Change(op='recolor',target='Jetson',color='green',text='',position='',reference='')],needs_clarification=False,clarification='')
    contract=compile_goal(g,scene(before));actions=candidates(contract,scene(before))
    colors={a['color'] for a in actions if a['op']=='recolor'}
    assert '#b2f2bb' in colors and '#ffc9c9' in colors and len(colors)>1
    text=remaining_goal(contract,scene(before))
    assert 'Make Jetson green' in text and 'Make Jetson red' not in text


def test_overlapping_and_ambiguous_layouts_are_rejected_before_ui_edits():
    before=raw_scene()
    g=Goal(changes=[Change(op='create_box',target='Extra',color='transparent',text='',position='center',reference='')],needs_clarification=False,clarification='')
    with pytest.raises(ValueError,match='overlaps'):
        compile_goal(g,scene(before))
    before['elements'] += rectangle('c','Camera',1070,320)
    with pytest.raises(ValueError,match='ambiguous'):
        compile_goal(goal(('rename','Camera','Sensor')),scene(before))


@pytest.mark.asyncio
async def test_cancel_during_drag_releases_mouse_button():
    from jetson_browser.whiteboard_browser import WhiteboardBrowser
    calls=[]
    async def move(*args, **kwargs):
        calls.append('move')
        if len(calls)>1:
            import asyncio
            raise asyncio.CancelledError()
    async def down(): calls.append('down')
    async def up(): calls.append('up')
    browser=WhiteboardBrowser()
    browser.page=SimpleNamespace(mouse=SimpleNamespace(move=move,down=down,up=up))
    import asyncio
    with pytest.raises(asyncio.CancelledError):
        await browser.drag((1,2),(3,4))
    assert calls[-1]=='up'


def test_execution_budgets_exclude_human_waiting_but_enforce_action_and_time_limits(monkeypatch):
    from jetson_browser.whiteboard_runner import remaining_budget
    trace=SimpleNamespace(started=100,state={'human_wait_seconds':900,'browser_actions':79})
    monkeypatch.setattr('jetson_browser.whiteboard_runner.time.monotonic',lambda:1100)
    assert remaining_budget(trace)==500
    trace.state['browser_actions']=80
    with pytest.raises(RuntimeError,match='budget'):
        remaining_budget(trace)
    trace.state.update(browser_actions=0,human_wait_seconds=0)
    with pytest.raises(RuntimeError,match='budget'):
        remaining_budget(trace)


def test_rejects_model_deletion_of_an_arrow_endpoint_that_the_user_requested_unchanged():
    before=raw_scene()
    bad=goal(('delete','Jetson'))
    request='Delete Robot Arm and its arrow from Jetson. Keep Camera, Jetson, and Monitor unchanged.'
    with pytest.raises(ValueError,match='unchanged'):
        validate_intent(bad,scene(before),request)
    with pytest.raises(ValueError,match='not explicitly authorized'):
        validate_intent(bad,scene(before),'Delete Camera and its connection to Jetson.')


@pytest.mark.asyncio
async def test_changed_scene_is_rejected_before_any_mouse_or_keyboard_input():
    from jetson_browser.browser import StaleObservation
    from jetson_browser.whiteboard_browser import WhiteboardBrowser
    browser=WhiteboardBrowser()
    before=raw_scene();after=copy.deepcopy(before);after['elements'][0]['x']=1000
    async def read(): return after
    browser.read=read
    with pytest.raises(StaleObservation,match='changed'):
        await browser.execute(before,{'op':'move','target':'a','x':350,'y':320})


def test_missing_preserved_object_is_never_recreated_with_a_new_identity():
    before=raw_scene();contract=compile_goal(goal(),scene(before))
    after=copy.deepcopy(before);after['elements']=after['elements'][2:]
    assert not verify(contract,scene(after))['passed']
    assert not any(a['op']=='create' for a in candidates(contract,scene(after)))


def test_interrupted_model_request_still_counts_and_has_recorded_latency(tmp_path,monkeypatch):
    from jetson_browser.trace import Trace
    from jetson_browser.whiteboard_runner import summarize_times
    monkeypatch.setattr('jetson_browser.trace.ROOT',tmp_path)
    trace=Trace('cancelled inference',True,scene='whiteboard',runs_root='whiteboard-runs')
    with pytest.raises(RuntimeError):
        with trace.operation('decide','laya','Laya request'):
            raise RuntimeError('Request interrupted')
    summarize_times(trace)
    assert trace.state['laya_calls']==1 and trace.state['laya_decision_seconds']>0


def test_text_palette_does_not_mislabel_native_orange_as_yellow():
    from jetson_browser.whiteboard_scene import color_value
    assert color_value('orange','text')=='#f08c00'
    assert color_value('yellow','rectangle')=='#ffec99'
    with pytest.raises(ValueError,match='Unsupported'):
        color_value('yellow','text')
