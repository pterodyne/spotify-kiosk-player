"""Persist display idle policy; no compositor processes run inside Flask."""
from ipaddress import ip_address
import json
import os
from pathlib import Path
import tempfile



def config_path():
    return Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'spotify-kiosk' / 'display.json'


def validate_minutes(minutes):
    if type(minutes) is not int or not 0 <= minutes <= 120:
        raise ValueError('minutes must be an integer from 0 (Never) to 120')
    return minutes


def read_minutes(path):
    try:
        return validate_minutes(json.loads(Path(path).read_text())['minutes'])
    except (OSError, ValueError, KeyError, TypeError):
        return 5


def save_minutes(path, minutes):
    validate_minutes(minutes)
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd, name = tempfile.mkstemp(prefix='.display-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump({'minutes': minutes}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def register_display_routes(app):
    from flask import jsonify, request, session
    @app.route('/api/system/screen-timeout', methods=['GET', 'POST'])
    def screen_timeout():
        token = session.get('token_info')
        if not isinstance(token, dict) or not token.get('access_token'):
            return jsonify(error='Authentication required'), 401
        path = app.config.get('DISPLAY_TIMEOUT_PATH') or config_path()
        if request.method == 'GET':
            return jsonify(minutes=read_minutes(path))
        try:
            local = ip_address(request.remote_addr or '').is_loopback
        except ValueError:
            local = False
        hosts = {'localhost:5000', '127.0.0.1:5000'}
        if not local or request.host not in hosts or request.headers.get('Origin') != 'http://' + request.host:
            return jsonify(error='Local trusted origin required'), 403
        if not request.is_json:
            return jsonify(error='JSON required'), 415
        body = request.get_json(silent=True)
        try:
            if not isinstance(body, dict) or set(body) != {'minutes'}:
                raise ValueError('Expected minutes only')
            save_minutes(path, body['minutes'])
        except ValueError as error:
            return jsonify(error=str(error)), 400
        except OSError:
            return jsonify(error='Cannot save display timeout'), 500
        return jsonify(minutes=body['minutes'])
