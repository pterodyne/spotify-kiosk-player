"""Run actual playback routes/decorator/translations without startup side effects."""
import ast
from functools import wraps
from pathlib import Path
from types import SimpleNamespace
import unittest


class SpotifyError(Exception):
    pass


def playback_scope(error=None, language=None, allowed=True, authenticated=True):
    tree = ast.parse((Path(__file__).parents[1] / 'app.py').read_text())
    names = {'get_user_language', 't', 'handle_spotify_error',
             'spotify_playback_action', 'play', 'play_track'}
    nodes = []
    calls = []
    def start(**kwargs):
        calls.append(kwargs)
        if error:
            raise SpotifyError(error)
    sp = SimpleNamespace(start_playback=start, devices=lambda: {'devices': [{'id': 'local', 'name': 'novaplayer'}]})
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'TRANSLATIONS' for t in node.targets):
            nodes.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in names:
            node.decorator_list = [d for d in node.decorator_list if isinstance(d, ast.Name) and d.id == 'spotify_playback_action']
            nodes.append(node)
    scope = {'wraps': wraps, 'session': {} if language is None else {'language': language},
             'jsonify': lambda value: value, 'request': SimpleNamespace(get_json=lambda: {'uri': 'spotify:track:test'}),
             'get_spotify_client': lambda: sp if authenticated else None,
             'playback_target': SimpleNamespace(resolve=lambda devices: devices[0]),
             'TargetError': ValueError, 'device_name_allowed': lambda device: allowed,
             'set_api_error': lambda: None, '_api_cooldown_seconds': 30,
             'spotipy': SimpleNamespace(exceptions=SimpleNamespace(SpotifyException=SpotifyError))}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'app.py', 'exec'), scope)
    return scope, calls


class PlaybackErrorTests(unittest.TestCase):
    def test_no_active_device_in_both_routes_is_actionable_and_localized(self):
        for route in ('play', 'play_track'):
            for lang in (None, 'en', 'unsupported', 'nl'):
                with self.subTest(route=route, language=lang):
                    scope, calls = playback_scope('http status: 404, Player command failed: No active device found', lang)
                    result, status = scope[route]()
                    self.assertEqual(status, 404)
                    if lang == 'nl':
                        self.assertIn('Spotify Connect', result['error'])
                        self.assertIn('Open Spotify', result['error'])
                    else:
                        self.assertIn('No active Spotify Connect device', result['error'])
                        self.assertIn('Open Spotify', result['error'])
                        self.assertIn('same account', result['error'])
                    self.assertEqual(calls, [{'device_id': 'local'}] if route == 'play' else [{'device_id': 'local', 'uris': ['spotify:track:test']}])

    def test_other_spotify_failures_are_localized_without_changing_status_or_shape(self):
        cases = [('max retries', 503, 'error.unavailable'),
                 ('rate limit', 429, 'error.rate_limit'),
                 ('503', 503, 'error.server_error'),
                 ('401 unauthorized', 401, 'error.session_expired'),
                 ('403 forbidden', 403, 'error.forbidden'),
                 ('unexpected Spotify failure', 500, 'error.spotify_failed')]
        for route in ('play', 'play_track'):
            for language in (None, 'en', 'nl', 'unsupported'):
                for error, status, key in cases:
                    with self.subTest(route=route, language=language, error=error):
                        scope, _ = playback_scope(error, language)
                        result, actual = scope[route]()
                        self.assertEqual(actual, status)
                        expected = scope['TRANSLATIONS']['nl' if language == 'nl' else 'en'].get(key)
                        self.assertIsNotNone(expected, 'missing translation: ' + key)
                        self.assertEqual(result['error'], expected)
                        if status == 403:
                            self.assertEqual(result['error_type'], 'forbidden')

    def test_success_auth_and_device_guards_preserve_playback_semantics(self):
        for route in ('play', 'play_track'):
            scope, calls = playback_scope()
            self.assertEqual(scope[route](), {'success': True})
            self.assertEqual(calls, [{'device_id': 'local'}] if route == 'play' else [{'device_id': 'local', 'uris': ['spotify:track:test']}])
            for kwargs, status in (({'authenticated': False}, 401), ({'allowed': False}, 403)):
                scope, calls = playback_scope(**kwargs)
                self.assertEqual(scope[route]()[1], status)
                self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()
