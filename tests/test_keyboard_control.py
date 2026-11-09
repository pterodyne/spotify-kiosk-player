"""Local keyboard route contract; never signal a real process."""
import importlib
import importlib.util
import os
import subprocess
import unittest
from unittest.mock import patch

from flask import Flask


class KeyboardControlTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.find_spec('keyboard_control')
        self.assertIsNotNone(spec, 'keyboard_control backend must exist')
        self.module = importlib.import_module('keyboard_control')
        self.app = Flask(__name__)
        self.app.secret_key = 'test-only'
        self.app.testing = True
        self.module.register_keyboard_routes(self.app)
        self.client = self.app.test_client()
        for host in ['http://127.0.0.1:5000', 'http://localhost:5000']:
            with self.client.session_transaction(base_url=host) as session:
                session['token_info'] = {'access_token': 'test'}

    def post(self, action='show', **kwargs):
        kwargs.setdefault('base_url', 'http://127.0.0.1:5000')
        kwargs.setdefault('headers', {'Origin': 'http://127.0.0.1:5000'})
        kwargs.setdefault('json', {'action': action})
        return self.client.post('/api/keyboard', **kwargs)

    @patch('subprocess.run')
    def test_show_fixed_command(self, run):
        run.return_value.returncode = 0
        response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {'supported': True})
        run.assert_called_once_with(
            ['pkill', '-USR2', '-u', str(os.getuid()), '-x', 'wvkbd-mobintl'],
            shell=False, timeout=1, check=False,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    @patch('subprocess.run')
    def test_rejects_untrusted_requests_before_command(self, run):
        cases = [
            {'environ_overrides': {'REMOTE_ADDR': '192.168.1.2'}},
            {'environ_overrides': {'REMOTE_ADDR': ''}},
            {'headers': {}},
            {'headers': {'Origin': 'null'}},
            {'headers': {'Origin': 'https://127.0.0.1:5000'}},
            {'headers': {'Origin': 'http://127.0.0.1:5000.evil'}},
            {'headers': {'Origin': 'http://localhost:5000/'}},
            {'base_url': 'http://evil.test:5000'},
            {'base_url': 'http://localhost:5001'},
            {'environ_overrides': {'REMOTE_ADDR': '10.0.0.1'},
             'headers': {'Origin': 'http://localhost:5000', 'X-Forwarded-For': '127.0.0.1'}},
        ]
        for options in cases:
            with self.subTest(options=options):
                self.assertEqual(self.post(**options).status_code, 403)
        run.assert_not_called()

    @patch('subprocess.run')
    def test_requires_session_not_global_cache(self, run):
        with self.client.session_transaction(base_url='http://127.0.0.1:5000') as session:
            session.clear()
        self.assertEqual(self.post().status_code, 401)
        run.assert_not_called()

    @patch('subprocess.run')
    def test_rejects_invalid_json_and_actions(self, run):
        for payload in [None, [], 'show', {}, {'action': 'exec'},
                        {'action': ['show']}, {'action': 'show', 'pid': 1},
                        {'action': 'show; reboot'}]:
            with self.subTest(payload=payload):
                response = self.post(json=payload)
                self.assertIn(response.status_code, (400, 415))
        self.assertEqual(self.post(json=None, data='{"action":"show"}',
                                   content_type='text/plain').status_code, 415)
        self.assertEqual(self.post(json=None, data='{',
                                   content_type='application/json').status_code, 400)
        run.assert_not_called()

    @patch('subprocess.run')
    def test_hide_and_ipv6_loopback(self, run):
        run.return_value.returncode = 0
        response = self.post('hide', base_url='http://localhost:5000',
                             headers={'Origin': 'http://localhost:5000'},
                             environ_overrides={'REMOTE_ADDR': '::1'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(run.call_args.args[0][1], '-USR1')

    @patch('subprocess.run')
    def test_unavailable_is_graceful(self, run):
        for error in [FileNotFoundError(), PermissionError(),
                      subprocess.TimeoutExpired('pkill', 1)]:
            with self.subTest(error=error):
                run.side_effect = error
                response = self.post()
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json, {'supported': False})
        run.side_effect = None
        for code in [1, 2, -9]:
            run.return_value.returncode = code
            self.assertEqual(self.post().json, {'supported': False})

    @patch('subprocess.run')
    def test_only_post(self, run):
        for method in ['GET', 'PUT', 'DELETE']:
            self.assertEqual(self.client.open('/api/keyboard', method=method).status_code, 405)
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
