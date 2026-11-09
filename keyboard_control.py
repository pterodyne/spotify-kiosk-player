"""Narrow local wvkbd control. Register on the kiosk Flask application only."""
from ipaddress import ip_address
import os
import subprocess

from flask import jsonify, request, session


_TRUSTED_HOSTS = frozenset({'127.0.0.1:5000', 'localhost:5000'})
_TRUSTED_ORIGINS = frozenset('http://' + host for host in _TRUSTED_HOSTS)


def register_keyboard_routes(app):
    """Register POST /api/keyboard with strict local browser/session checks.

    Uses the application's signed session['token_info']['access_token']; never
    restores credentials from a shared token cache. No app import is required.
    Keep the WSGI peer address intact: do not trust forwarded client addresses
    from untrusted proxies. This endpoint deliberately grants no CORS access.
    """
    @app.post('/api/keyboard')
    def keyboard_control():
        try:
            local_peer = ip_address(request.remote_addr or '').is_loopback
        except ValueError:
            local_peer = False
        if (not local_peer or request.host not in _TRUSTED_HOSTS
                or request.headers.get('Origin') not in _TRUSTED_ORIGINS):
            return jsonify(error='Local trusted origin required'), 403

        token_info = session.get('token_info')
        if not isinstance(token_info, dict) or not token_info.get('access_token'):
            return jsonify(error='Authentication required'), 401
        if not request.is_json:
            return jsonify(error='JSON required'), 415
        body = request.get_json(silent=True)
        if (not isinstance(body, dict) or set(body) != {'action'}
                or body['action'] not in ('show', 'hide')):
            return jsonify(error='Expected action show or hide'), 400

        signal = '-USR2' if body['action'] == 'show' else '-USR1'
        try:
            result = subprocess.run(
                ['pkill', signal, '-u', str(os.getuid()), '-x', 'wvkbd-mobintl'],
                shell=False, timeout=1, check=False,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired):
            return jsonify(supported=False)
        return jsonify(supported=result.returncode == 0)
