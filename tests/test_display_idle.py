import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_config_defaults_atomic_permissions_and_validation(tmp_path):
    import display_timeout as d
    path = tmp_path / 'settings' / 'display.json'
    assert d.read_minutes(path) == 5
    d.save_minutes(path, 0)
    assert d.read_minutes(path) == 0
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert not list(path.parent.glob('.display-*'))
    path.write_text('{broken')
    assert d.read_minutes(path) == 5
    d.save_minutes(path, 120)
    assert d.read_minutes(path) == 120
    for value in (True, -1, 121, '5', 1.5):
        try:
            d.save_minutes(path, value)
        except ValueError:
            pass
        else:
            raise AssertionError(value)


def test_routes_auth_validation_and_persistence(tmp_path):
    from flask import Flask
    import display_timeout as d
    app = Flask(__name__)
    app.secret_key = 'test'
    app.config['DISPLAY_TIMEOUT_PATH'] = tmp_path / 'display.json'
    d.register_display_routes(app)
    client = app.test_client()
    assert client.get('/api/system/screen-timeout').status_code == 401
    with client.session_transaction() as session:
        session['token_info'] = {'access_token': 'test'}
    assert client.get('/api/system/screen-timeout').json == {'minutes': 5}
    headers = {'Origin': 'http://localhost:5000'}
    assert client.post('/api/system/screen-timeout', base_url='http://localhost:5000', json={'minutes': 0}, headers=headers).json == {'minutes': 0}
    for body in ({'minutes': 121}, {'minutes': True}, {'minutes': 5, 'output': 'DPI-1;exec bad'}):
        assert client.post('/api/system/screen-timeout', base_url='http://localhost:5000', json=body, headers=headers).status_code == 400
    assert client.post('/api/system/screen-timeout', json={'minutes': 3}).status_code == 403


def test_supervisor_refresh_disables_and_fixed_commands(tmp_path, monkeypatch):
    import display_timeout as d
    spec = importlib.util.spec_from_file_location('display_idle', ROOT / 'scripts/display-idle.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls = []
    class Child:
        def terminate(self): calls.append('terminate')
        def wait(self, timeout): calls.append('wait')
        def poll(self): return None
    monkeypatch.setattr(module.subprocess, 'Popen', lambda args: calls.append(args) or Child())
    monkeypatch.setattr(module, 'power_on', lambda output: calls.append(('on', output)))
    path = tmp_path / 'display.json'
    supervisor = module.Supervisor(path, 'DPI-1')
    supervisor.refresh()
    args = calls[-1]
    assert args[:7] == ['swayidle', '-C', '/dev/null', '-w', '-S', 'seat0', 'timeout']
    assert args[7] == '300'
    assert args[8:] == ['swaymsg output DPI-1 power off', 'resume', 'swaymsg output DPI-1 power on']
    d.save_minutes(path, 2)
    supervisor.refresh()
    assert calls[-1][7] == '120'
    d.save_minutes(path, 0)
    supervisor.refresh()
    assert calls[-1] == ('on', 'DPI-1')
    assert supervisor.child is None
    import pytest
    with pytest.raises(ValueError): module.Supervisor(path, 'DPI-1;exec bad')
