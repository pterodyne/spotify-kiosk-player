"""AST-isolated search routes: no OAuth, hardware or network startup."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


class SpotifyError(Exception):
    def __init__(self, status):
        super().__init__('secret token upstream details')
        self.http_status = status


def search(sp, **params):
    tree = ast.parse((Path(__file__).parents[1] / 'app.py').read_text())
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef)
             and n.name == 'search_catalog']
    for node in nodes:
        node.decorator_list = []
    scope = {'get_spotify_client': lambda: sp, 'jsonify': lambda value: value,
             'request': SimpleNamespace(args=params),
             'spotipy': SimpleNamespace(exceptions=SimpleNamespace(SpotifyException=SpotifyError))}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'app.py', 'exec'), scope)
    return scope['search_catalog']()


class SearchTests(unittest.TestCase):
    def test_track_envelope_normalization_single_account_market_request(self):
        calls = []
        track = dict(id='t', uri='spotify:track:t', name='Song',
                     artists=[{'name': 'Artist'}], duration_ms=123,
                     album={'name': 'Record', 'uri': 'spotify:album:r', 'images': [{'url': 'cover'}]})
        def request(**kwargs):
            calls.append(kwargs)
            return {'tracks': {'items': [track], 'next': 'next-page'}}
        result = search(SimpleNamespace(search=request), q='  song  ', type='track', offset='10')
        self.assertEqual(result, {'items': [dict(id='t', uri='spotify:track:t', name='Song',
            artist='Artist', album='Record', album_uri='spotify:album:r', duration_ms=123,
            image='cover')], 'offset': 10, 'next_offset': 20, 'type': 'track', 'query': 'song'})
        self.assertEqual(calls, [dict(q='song', type='track', offset=10, limit=10)])

    def test_validation_rejects_invalid_input_without_search(self):
        for params in ({}, {'q': ' '}, {'q': 'x' * 201}, {'q': 'x', 'type': 'playlist'},
                       {'q': 'x', 'offset': '-1'}, {'q': 'x', 'offset': '1001'},
                       {'q': 'x', 'offset': '1.5'}, {'q': 'x', 'offset': 'abc'}):
            with self.subTest(params=params):
                result, status = search(SimpleNamespace(), **params)
                self.assertEqual(status, 400)
                self.assertIn('error', result)

    def test_artist_album_normalization_and_bounded_next(self):
        for kind in ('artist', 'album'):
            item = dict(id='a', uri='spotify:' + kind + ':a', name='Name', images=None,
                        release_date='2026', total_tracks=12)
            for offset, next_link, expected_next in ((0, None, None), (990, 'next', 1000), (1000, 'next', None)):
                with self.subTest(kind=kind, offset=offset):
                    sp = SimpleNamespace(search=lambda **kw: {kind + 's': {'items': [None, item], 'next': next_link}})
                    result = search(sp, q='x', type=kind, offset=str(offset))
                    normalized = {'id': 'a', 'uri': item['uri'], 'name': 'Name', 'image': None}
                    if kind == 'album':
                        normalized.update(release_date='2026', total_tracks=12)
                    self.assertEqual(result['items'], [normalized])
                    self.assertEqual(result['next_offset'], expected_next)

    def test_upstream_errors_preserve_status_without_secrets(self):
        for status in (401, 403, 429, 500):
            def fail(**kwargs):
                raise SpotifyError(status)
            result, actual = search(SimpleNamespace(search=fail), q='x')
            self.assertEqual(actual, status if status != 500 else 502)
            self.assertNotIn('secret', str(result))
            self.assertTrue(result['error'])

    def test_unexpected_client_error_is_sanitized(self):
        def fail(**kwargs):
            raise RuntimeError('secret')
        result, status = search(SimpleNamespace(search=fail), q='x')
        self.assertEqual(status, 502)
        self.assertNotIn('secret', str(result))

    def test_authentication_required(self):
        self.assertEqual(search(None, q='x'), ({'error': 'Not authenticated'}, 401))


if __name__ == '__main__':
    unittest.main()
