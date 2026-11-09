"""Dependency-isolated route tests; no hardware, OAuth, or network startup."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


def routes(sp):
    tree = ast.parse((Path(__file__).parents[1] / 'app.py').read_text())
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and
             (n.name.startswith('_spotify_') or n.name in {
                 'get_playlists', 'get_artist_albums', 'get_artist_top_tracks',
                 'get_album_tracks', 'get_playlist_tracks'})]
    for node in nodes:
        node.decorator_list = []
    scope = {'get_spotify_client': lambda: sp, 'jsonify': lambda x: x,
             'spotipy': SimpleNamespace(exceptions=SimpleNamespace(SpotifyException=SpotifyError))}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'app.py', 'exec'), scope)
    return scope


class SpotifyError(Exception):
    def __init__(self, status):
        self.http_status = status


class CompatibilityTests(unittest.TestCase):
    def test_playlist_summary_renamed_fields_and_pagination(self):
        page2 = {'items': [{'id': 'b', 'name': 'B', 'images': None, 'tracks': {'total': 2}}], 'next': None}
        sp = SimpleNamespace(current_user_playlists=lambda **kw: {
            'items': [{'id': 'a', 'name': 'A', 'images': [], 'items': {'total': 1}}], 'next': 'page2'},
            next=lambda page: page2)
        result = routes(sp)['get_playlists']()
        self.assertEqual([p['tracks_total'] for p in result], [1, 2])

    def test_albums_use_ten_account_market_and_all_pages(self):
        calls = []
        album = dict(id='a', uri='spotify:album:a', name='A', images=[], release_date='2026', total_tracks=1)
        def albums(*args, **kw):
            calls.append(kw)
            if kw.get('limit') != 10 or 'country' in kw:
                raise SpotifyError(400)
            return {'items': [album], 'next': 'page2'}
        sp = SimpleNamespace(artist_albums=albums, next=lambda page: {'items': [dict(album, id='b')], 'next': None})
        result = routes(sp)['get_artist_albums']('artist')
        self.assertEqual([a['id'] for a in result], ['a', 'b'])
        self.assertEqual(calls, [{'album_type': 'album', 'limit': 10}])

    def test_playlist_forbidden_explains_ownership_restriction(self):
        def denied(*args, **kwargs):
            raise SpotifyError(403)
        result, status = routes(SimpleNamespace(_get=denied))['get_playlist_tracks']('p')
        self.assertEqual(status, 403)
        self.assertEqual(result['error_type'], 'playlist_access_restricted')

    def test_pagination_repeated_link_stops(self):
        page = {'items': [], 'next': 'same'}
        with self.assertRaisesRegex(ValueError, 'repeated'):
            routes(None)['_spotify_pages'](SimpleNamespace(next=lambda p: page), page)

    def test_top_tracks_forbidden_is_explicit_unsupported(self):
        def top(*args, **kwargs):
            self.assertNotIn('country', kwargs)
            raise SpotifyError(403)
        result, status = routes(SimpleNamespace(_get=top))['get_artist_top_tracks']('a')
        self.assertEqual(status, 403)
        self.assertEqual(result['error_type'], 'unsupported_feature')
        self.assertFalse(result['supported'])
        self.assertNotIn('tracks', result)

    def test_playlist_items_new_endpoint_paginated_and_legacy_fields(self):
        track = dict(id='t', uri='spotify:track:t', name='T', artists=[{'name': 'A'}],
                     album={'name': 'Album', 'images': []}, duration_ms=42, type='track')
        def get(path, **kwargs):
            self.assertEqual(path, 'playlists/p/items')
            self.assertEqual(kwargs['limit'], 10)
            return {'items': [{'item': track}, {'item': None}, {'item': {'type': 'episode'}}], 'next': 'page2'}
        sp = SimpleNamespace(_get=get, next=lambda p: {'items': [{'track': dict(track, id='u')}], 'next': None})
        result = routes(sp)['get_playlist_tracks']('p')
        self.assertEqual([t['id'] for t in result], ['t', 'u'])

    def test_album_tracks_all_pages_account_market(self):
        track = dict(id='t', uri='spotify:track:t', name='T', artists=[], duration_ms=42, track_number=1)
        def tracks(*args, **kwargs):
            self.assertEqual(kwargs, {'limit': 10})
            return {'items': [track], 'next': 'page2'}
        sp = SimpleNamespace(album=lambda a: {'images': [], 'uri': 'album:a', 'name': 'A'},
                             album_tracks=tracks, next=lambda p: {'items': [dict(track, id='u')], 'next': None})
        self.assertEqual([t['id'] for t in routes(sp)['get_album_tracks']('a')], ['t', 'u'])


if __name__ == '__main__':
    unittest.main()
