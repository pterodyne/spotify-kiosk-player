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


def read_seconds(path):
    try:
        data = json.loads(Path(path).read_text())
        if not isinstance(data, dict):
            raise ValueError('Expected object')
        if set(data) == {'minutes'}:
            return validate_minutes(data['minutes']) * 60
        if (set(data) != {'seconds'} or type(data['seconds']) is not int
                or not 0 <= data['seconds'] <= 7200
                or (data['seconds'] != 30 and data['seconds'] % 60 != 0)):
            raise ValueError('Invalid seconds config')
        return data['seconds']
    except (OSError, ValueError, KeyError, TypeError):
        return 300


def read_minutes(path):
    # Never floor a sub-minute timeout to zero (which means disabled).
    seconds = read_seconds(path)
    return seconds // 60 if seconds % 60 == 0 else seconds / 60


def save_minutes(path, minutes):
    save_seconds(path, validate_minutes(minutes) * 60, legacy=True)


def save_seconds(path, seconds, *, legacy=False):
    if type(seconds) is not int or (seconds not in (0, 30, 60, 300, 1800) and not (legacy and 0 <= seconds <= 7200)):
        raise ValueError('seconds must be one of 0, 30, 60, 300, 1800')
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd, name = tempfile.mkstemp(prefix='.display-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump({'seconds': seconds}, stream)
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
            if request.args.get('unit') == 'seconds':
                return jsonify(seconds=read_seconds(path))
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
            if not isinstance(body, dict) or set(body) not in ({'minutes'}, {'seconds'}):
                raise ValueError('Expected seconds or legacy minutes only')
            if 'seconds' in body:
                save_seconds(path, body['seconds'])
            else:
                save_minutes(path, body['minutes'])
        except ValueError as error:
            return jsonify(error=str(error)), 400
        except OSError:
            return jsonify(error='Cannot save display timeout'), 500
        return jsonify(body)
