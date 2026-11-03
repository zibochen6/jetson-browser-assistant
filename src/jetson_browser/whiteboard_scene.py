"""Desired-state compilation and independent verification of public scene reads.

This module never operates the browser. A desired state is a contract, not an
ordered script; the decision model chooses which available change to make next.
"""
import hashlib
import json
import math
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Change(BaseModel):
    model_config = ConfigDict(extra='forbid')
    op: Literal['create_box', 'create_text', 'recolor', 'move', 'rename', 'delete', 'connect', 'disconnect']
    target: str = Field(max_length=32)
    text: str = Field(max_length=32)
    color: Literal['', 'transparent', 'red', 'green', 'blue', 'yellow', 'orange', 'black']
    position: Literal['', 'keep', 'left', 'center', 'right', 'above', 'below']
    reference: str = Field(max_length=32)


class Goal(BaseModel):
    model_config = ConfigDict(extra='forbid')
    changes: list[Change] = Field(max_length=20)
    needs_clarification: bool
    clarification: str = Field(max_length=300)


COLORS = {'transparent': 'transparent', 'red': '#ffc9c9', 'green': '#b2f2bb', 'blue': '#a5d8ff', 'yellow': '#ffec99'}
STROKES = {'black': '#1e1e1e', 'red': '#e03131', 'green': '#2f9e44', 'blue': '#1971c2', 'orange': '#f08c00'}
TOLERANCE = 16


def digest(raw):
    return hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def scene(raw):
    elements = [e for e in raw['elements'] if not e.get('isDeleted')]
    by_id = {e['id']: e for e in elements}
    shapes, edges = {}, {}
    for e in elements:
        if e['type'] not in ('rectangle', 'text') or (e['type'] == 'text' and e.get('containerId')):
            continue
        text = e.get('text', '') if e['type'] == 'text' else '\n'.join(
            by_id[b['id']].get('text', '') for b in e.get('boundElements') or []
            if b.get('type') == 'text' and b['id'] in by_id)
        shapes[e['id']] = {'id': e['id'], 'kind': e['type'], 'text': text,
            'x': e['x'], 'y': e['y'], 'width': e['width'], 'height': e['height'],
            'color': e['strokeColor'] if e['type'] == 'text' else e['backgroundColor'],
            'stroke': e['strokeColor'], 'angle': e.get('angle', 0),
            'label_colors': {b['id']:by_id[b['id']].get('strokeColor') for b in e.get('boundElements') or []
                if b.get('type')=='text' and b['id'] in by_id}}
    for e in elements:
        if e['type'] == 'arrow':
            edges[e['id']] = {'id': e['id'], 'source': (e.get('startBinding') or {}).get('elementId'),
                'destination': (e.get('endBinding') or {}).get('elementId'), 'endArrowhead': e.get('endArrowhead'),
                'stroke': e.get('strokeColor')}
    return {'shapes': shapes, 'edges': edges, 'raw': raw}


def summary(current):
    return {'objects': list(current['shapes'].values()), 'connections': list(current['edges'].values())}


def color_value(name, kind):
    palette = STROKES if kind == 'text' else COLORS
    if name not in palette:
        raise ValueError(f'Unsupported {kind} color: {name}')
    return palette[name]


def validate_intent(goal, current, request):
    """Conservative English provenance/preservation guards, before any UI input.

    These checks constrain the supported first-version language; they do not
    claim to be a second natural-language model.
    """
    keep_clauses = re.findall(r'\bkeep\b([^.!?]*)', request, flags=re.I)
    for change in goal.changes:
        label = current['shapes'].get(change.target, {}).get('text', change.target)
        if not label or label.casefold() not in request.casefold():
            raise ValueError(f'Proposed edit targets "{label}", which was not explicitly named in the instruction')
        for clause in keep_clauses:
            if label.casefold() in clause.casefold() and re.search(r'\b(unchanged|as is|intact)\b', clause, re.I):
                raise ValueError(f'"{label}" was explicitly requested unchanged, but the proposal edits it')
        if change.op == 'delete':
            expression = r'\b(?:delete|remove)\s+(?:(?:the|box|rectangle|text|labeled|labelled)\s+)*["\x27]?' + re.escape(label) + r'\b'
            if not re.search(expression, request, re.I):
                raise ValueError(f'Deletion of "{label}" is not explicitly authorized; say Delete {label}')


def compile_goal(goal, baseline):
    """Resolve object identities once; preserve everything except explicit changes."""
    desired = {k: dict(v, move=False, existing=True) for k, v in baseline['shapes'].items()}
    names = {}
    for k, v in desired.items():
        names.setdefault(v['text'].casefold(), []).append(k)

    def resolve(label):
        if label in desired:
            return label
        ids = names.get(label.casefold(), [])
        if len(ids) != 1 or ids[0] not in desired:
            raise ValueError(f'Object "{label}" is missing or ambiguous; use a unique existing label')
        return ids[0]

    for c in goal.changes:
        if c.op.startswith('create_'):
            if not c.target.strip() or names.get(c.target.casefold()):
                raise ValueError(f'New object label "{c.target}" must be nonempty and unique')
            key = 'new:' + c.target
            kind = 'rectangle' if c.op == 'create_box' else 'text'
            desired[key] = {'id': None, 'kind': kind, 'text': c.target, 'x': 710, 'y': 320,
                'width': 200, 'height': 112, 'color': color_value(c.color or ('black' if kind == 'text' else 'transparent'), kind),
                'stroke': '#1e1e1e', 'angle': 0, 'move': True, 'existing': False}
            names[c.target.casefold()] = [key]
    edges = {(e['source'], e['destination']) for e in baseline['edges'].values()}
    if any(a not in desired or b not in desired for a, b in edges):
        raise ValueError('An existing arrow has missing bindings; repair it manually before this task')
    deleted = set()
    for c in goal.changes:
        target = resolve(c.target)
        if c.op == 'delete':
            deleted.add(target)
        elif c.op == 'rename':
            if not c.text.strip():
                raise ValueError('A replacement label is required')
            desired[target]['text'] = c.text
        elif c.op == 'recolor':
            desired[target]['color'] = color_value(c.color, desired[target]['kind'])
        elif c.op in ('connect', 'disconnect'):
            other = resolve(c.reference)
            if target == other:
                raise ValueError('Self connections are outside the MVP')
            pair = (target, other)
            if c.op == 'connect':
                edges.add(pair)
            else:
                edges.discard(pair)
    # Relations are declarative constraints. Solve their grid coordinates in
    # dependency order; this is deterministic layout, not model spatial reasoning.
    pending = [c for c in goal.changes if c.op in ('create_box', 'create_text', 'move') and c.position not in ('', 'keep')]
    resolved = set(desired) - {resolve(c.target) for c in pending}
    for _ in range(len(pending) + 1):
        remaining = []
        for c in pending:
            key = resolve(c.target)
            ref = resolve(c.reference) if c.reference else None
            if ref and ref not in resolved:
                remaining.append(c)
                continue
            x, y = (desired[ref]['x'], desired[ref]['y']) if ref else (710, 320)
            if ref:
                dx, dy = {'left': (-360, 0), 'right': (360, 0), 'above': (0, -240), 'below': (0, 240), 'center': (0, 0)}[c.position]
            else:
                dx, dy = {'left': (-360, 0), 'right': (360, 0), 'above': (0, -240), 'below': (0, 240), 'center': (0, 0)}[c.position]
            desired[key].update(x=x + dx, y=y + dy, move=True)
            resolved.add(key)
        if not remaining:
            break
        if len(remaining) == len(pending):
            raise ValueError('Position references form a cycle; specify one absolute center/left/right anchor')
        pending = remaining
    for key in deleted:
        desired.pop(key)
    edges = {(a, b) for a, b in edges if a not in deleted and b not in deleted}
    if len(desired) > 12:
        raise ValueError('The first version supports up to 12 labeled objects')
    for v in desired.values():
        if not (300 <= v['x'] <= 1190 and 160 <= v['y'] <= 760) or v['angle'] != 0:
            raise ValueError('Layout exceeds the supported canvas area or contains rotated objects')
    positions = [v for v in desired.values()]
    for i, a in enumerate(positions):
        for b in positions[i + 1:]:
            if abs(a['x'] - b['x']) < 180 and abs(a['y'] - b['y']) < 90:
                raise ValueError('Requested placement overlaps another object; specify a separate position')
    return {'shapes': desired, 'edges': [list(e) for e in sorted(edges)], 'deleted': sorted(deleted),
        'protected_text_ids': [e['id'] for e in baseline['raw']['elements'] if e['type'] == 'text'
            and e['id'] not in deleted and e.get('containerId') not in deleted],
        'baseline': summary(baseline), 'unsupported_ids': sorted(e['id'] for e in baseline['raw']['elements']
            if e['type'] not in ('rectangle', 'text', 'arrow'))}


def match_shapes(contract, current):
    matches = {}
    for key, want in contract['shapes'].items():
        if want['existing']:
            if key in current['shapes']:
                matches[key] = key
        else:
            found = [s['id'] for s in current['shapes'].values() if s['kind'] == want['kind'] and s['text'] == want['text']]
            if len(found) == 1:
                matches[key] = found[0]
    return matches


def verify(contract, current):
    """All evidence comes from the supplied fresh scene, never execution receipts."""
    checks = []

    def check(name, ok, **detail):
        checks.append({'check': name, 'passed': bool(ok), **detail})

    matches = match_shapes(contract, current)
    for key, want in contract['shapes'].items():
        got = current['shapes'].get(matches.get(key))
        check('object', got is not None, target=want['text'])
        if not got:
            continue
        check('label', got['text'] == want['text'], target=key, actual=got['text'], expected=want['text'])
        check('color', got['color'] == want['color'], target=key, actual=got['color'], expected=want['color'])
        check('position', math.hypot(got['x'] - want['x'], got['y'] - want['y']) <= TOLERANCE,
              target=key, actual=[got['x'], got['y']], expected=[want['x'], want['y']], tolerance=TOLERANCE)
        check('kind_and_angle', got['kind'] == want['kind'] and got['angle'] == want['angle'], target=key)
        check('stroke_preserved', got['stroke'] == want['stroke'] or want['kind'] == 'text', target=key)
        if want['existing'] and 'label_colors' in want:
            check('label_colors_preserved', got['label_colors']==want['label_colors'], target=key)
    actual_pairs = {(e['source'], e['destination']) for e in current['edges'].values() if e['endArrowhead']}
    expected_pairs = {(matches.get(a), matches.get(b)) for a, b in contract['edges']}
    check('connections', None not in {i for pair in expected_pairs for i in pair} and actual_pairs == expected_pairs,
        actual=[list(p) for p in actual_pairs], expected=[list(p) for p in expected_pairs])
    check('no_extra_objects', set(current['shapes']) == set(matches.values()))
    check('no_extra_or_unbound_arrows', len(current['edges']) == len(contract['edges']))
    check('deleted_objects_absent', not (set(contract['deleted']) & set(current['shapes'])))
    baseline_edges = contract['baseline']['connections']
    expected_keys = {tuple(p) for p in contract['edges']}
    for e in baseline_edges:
        if (e['source'], e['destination']) in expected_keys:
            check('existing_connection_id_preserved', e['id'] in current['edges'], target=e['id'])
            check('existing_connection_style_preserved', current['edges'].get(e['id'], {}).get('stroke') == e.get('stroke'), target=e['id'])
    raw_by_id = {e['id']: e for e in current['raw']['elements']}
    check('other_element_ids_preserved', all(i in raw_by_id for i in contract['unsupported_ids']))
    check('existing_text_ids_preserved', all(i in raw_by_id for i in contract.get('protected_text_ids', [])))
    return {'passed': all(c['passed'] for c in checks), 'checks': checks,
            'matched_ids': matches, 'actual': summary(current)}


def candidates(contract, current):
    """Offer available capabilities, not a preordered or single-action script."""
    out = []
    matches = match_shapes(contract, current)

    def add(label, op, **params):
        n = str(len(out) + 1)
        out.append({'id': 'wb' + n, 'node': n, 'kind': 'click', 'role': 'button', 'label': label,
                    'source': 'validated_canvas_ui_capability', 'op': op, **params})

    for key, want in contract['shapes'].items():
        ident = matches.get(key)
        if ident is None:
            if not want['existing']:
                add(f'Create {want["kind"]}: {want["text"]}', 'create', key=key, desired=want)
            continue
        got = current['shapes'][ident]
        if got['text'] != want['text']:
            add(f'Rename {got["text"]} to {want["text"]}', 'rename', target=ident, text=want['text'])
        if got['color'] != want['color']:
            palette = STROKES if got['kind'] == 'text' else COLORS
            for name, value in palette.items():
                if got['color'] != value:
                    add(f'Make {got["text"]} {name}', 'recolor', target=ident, color=value)
        if math.hypot(got['x'] - want['x'], got['y'] - want['y']) > TOLERANCE:
            add(f'Move {got["text"]} to requested position', 'move', target=ident, x=want['x'], y=want['y'])
    for ident in contract['deleted']:
        if ident in current['shapes']:
            add(f'Delete {current["shapes"][ident]["text"]}', 'delete', target=ident)
    actual_pairs = {(e['source'], e['destination']) for e in current['edges'].values()}
    desired_pairs = {(matches.get(a), matches.get(b)) for a, b in contract['edges'] if a in matches and b in matches}
    for a, b in sorted(desired_pairs):
        if (a, b) not in actual_pairs:
            add(f'Connect {current["shapes"][a]["text"]} to {current["shapes"][b]["text"]}', 'connect', source_id=a, destination_id=b)
    # Unbound/new incorrect arrows and explicit disconnects can be removed via UI.
    for e in current['edges'].values():
        if (e['source'], e['destination']) not in desired_pairs and not any(
                e['source'] == matches.get(a) and b not in matches for a, b in contract['edges']):
            add(arrow_removal_label(contract, current, e), 'delete_arrow', target=e['id'])
    # Real selections are useful alternatives for inspection. They are omitted
    # only when already selected, not because they fail to advance a planned path.
    selected = current['raw']['appState']['selectedElementIds']
    for s in current['shapes'].values():
        if s['id'] not in selected:
            add(f'Select {s["text"]}', 'select', target=s['id'])
    return out


def remaining_goal(contract, current):
    """Describe *all* unmet requirements, without prescribing the next action."""
    matches = match_shapes(contract, current)
    requirements = []
    reverse_colors = {**{v: k for k, v in COLORS.items()}, **{v: k for k, v in STROKES.items()}}
    for key, want in contract['shapes'].items():
        got = current['shapes'].get(matches.get(key))
        if not got:
            requirements.append(f'Create a {want["kind"]} labeled {want["text"]}')
            continue
        if got['text'] != want['text']:
            requirements.append(f'Rename {got["text"]} to {want["text"]}')
        if got['color'] != want['color']:
            requirements.append(f'Make {got["text"]} {reverse_colors.get(want["color"], want["color"])}')
        if math.hypot(got['x'] - want['x'], got['y'] - want['y']) > TOLERANCE:
            requirements.append(f'Move {got["text"]} to requested position ({want["x"]},{want["y"]})')
    actual = {(e['source'], e['destination']) for e in current['edges'].values()}
    for a, b in contract['edges']:
        if a not in matches or b not in matches or (matches[a], matches[b]) not in actual:
            requirements.append(f'Connect {contract["shapes"][a]["text"]} to {contract["shapes"][b]["text"]}')
    for ident in contract['deleted']:
        if ident in current['shapes']:
            requirements.append(f'Delete {current["shapes"][ident]["text"]}')
    desired_pairs = {(matches.get(a), matches.get(b)) for a, b in contract['edges'] if a in matches and b in matches}
    for edge in current['edges'].values():
        if (edge['source'], edge['destination']) not in desired_pairs:
            requirements.append(arrow_removal_label(contract, current, edge))
    return '. '.join(requirements) + '. Keep all other labels, colors, objects and connections.'


def arrow_removal_label(contract, current, edge):
    previous = next((e for e in contract['baseline']['connections'] if e['id'] == edge['id']), edge)
    names = {s['id']: s['text'] for s in contract['baseline']['objects']}
    names.update({k:s['text'] for k,s in current['shapes'].items()})
    return f'Remove arrow {names.get(previous["source"], "unbound")} to {names.get(previous["destination"], "unbound")}'
