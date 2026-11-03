import json
import os
from pathlib import Path

ROOT = Path(os.environ.get('JETSON_BROWSER_ROOT', Path(__file__).resolve().parents[2])).expanduser().resolve()


def settings():
    config = json.loads((ROOT / 'config.json').read_text())
    local = ROOT / 'config.local.json'
    if local.exists():
        overrides = json.loads(local.read_text())
        if not isinstance(overrides, dict):
            raise ValueError('config.local.json must contain a JSON object')
        unknown = overrides.keys() - config.keys()
        if unknown:
            raise ValueError('Unknown local configuration keys: ' + ', '.join(sorted(unknown)))
        config.update(overrides)
    for name in ('mtp', 'record_video'):
        if not isinstance(config[name], bool):
            raise ValueError(f'{name} must be true or false')
    for name, minimum, maximum in [('max_actions', 1, 200), ('timeout_seconds', 1, 3600),
            ('model_startup_timeout_seconds', 1, 3600), ('context_size', 256, 32768), ('draft_depth', 1, 8)]:
        value = config[name]
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise ValueError(f'{name} must be an integer between {minimum} and {maximum}')
    for name, port in [('service_url', 8790), ('laya_url', 8791), ('qwen_url', 8792)]:
        if config[name] != f'http://127.0.0.1:{port}':
            raise ValueError(f'{name} must be http://127.0.0.1:{port}; remote endpoints and custom ports are unsupported')
    return config


def desktop_env():
    env = dict(os.environ)
    env.setdefault('DISPLAY', ':0')
    env.setdefault('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')
    if not env.get('XAUTHORITY'):
        for path in (Path(env['XDG_RUNTIME_DIR']) / 'gdm/Xauthority', Path.home() / '.Xauthority'):
            if path.is_file():
                env['XAUTHORITY'] = str(path)
                break
    return env
