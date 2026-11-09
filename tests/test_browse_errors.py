"""Execute the real browsing loaders in Node with minimal DOM/network seams."""
from pathlib import Path
import subprocess
import unittest


APP = Path(__file__).resolve().parents[1] / 'static/js/app.js'
LOADERS = ['loadPlaylists', 'loadArtists', 'loadTracks', 'loadTracksById',
           'loadArtistAlbums',
           'loadAlbumTracks', 'loadAlbumTracksById']


def run_loader(name, scenario):
    script = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert/strict');
const source = fs.readFileSync(process.argv[1], 'utf8');
const name = process.argv[2], scenario = process.argv[3];
const functions = [...source.matchAll(/^(?:async )?function \w+\([^\n]*\) \{[\s\S]*?^\}/gm)];
const selected = functions.filter(m => /function (loadPlaylists|loadArtists|loadTracks|loadTracksById|loadArtistAlbums|loadAlbumTracks|loadAlbumTracksById|readBrowseList|showBrowseError)\(/.test(m[0])).map(m => m[0]).join('\n');
function element() {
    return {innerHTML: '', textContent: '', style: {}, children: [],
        classList: {add() {}, remove() {}, toggle() {}},
        replaceChildren(...children) {this.innerHTML = ''; this.children = children;}};
}
const tracks = element(), playlists = element(), writes = [], rendered = [];
const message = '<img src=x onerror=alert(1)> Spotify access denied';
const data = scenario === 'success' ? [{id: 'real-track'}] :
    scenario === 'empty' || scenario === 'http-array' ? [] :
    scenario === 'malformed' ? {unexpected: true} : {error: message, code: 'forbidden'};
let requests = 0;
const cache = new Map();
const ctx = {
    console: {error() {}}, tracksContainer: tracks, playlistsContainer: playlists,
    albumBackBtn: element(), currentPlaylistId: null, currentArtistId: null,
    currentAlbumId: null,
    CACHE_KEYS: {PLAYLISTS: 'p', ARTISTS: 'a', TRACKS_PREFIX: 'pt',
        ARTIST_ALBUMS_PREFIX: 'aa', ALBUM_TRACKS_PREFIX: 'al'},
    getCache: key => cache.get(key), setCache: (key, value) => {writes.push(value); cache.set(key, value);},
    renderTracks: value => rendered.push(value), renderAlbumTracks: value => rendered.push(value),
    renderPlaylists: value => rendered.push(value), renderArtists: value => rendered.push(value),
    renderAlbums: value => rendered.push(value), highlightArtistItem() {}, updateURL() {},
    t: key => key === 'panel.albums' ? 'Albums' : key,
    document: {getElementById: () => element(), querySelectorAll: () => [], createElement: element},
    fetch: async () => {requests++; return {ok: !['error', 'http-array'].includes(scenario), status: 403,
        json: async () => {if (scenario === 'invalid-json') throw new SyntaxError('bad JSON'); return data;}};}
};
vm.createContext(ctx); vm.runInContext(selected, ctx);
(async () => {
    await ctx[name]('id', element());
    if (['success', 'empty'].includes(scenario)) {
        assert.deepEqual(writes, [data]); assert.deepEqual(rendered, [data]);
        await ctx[name]('id', element());
        assert.equal(requests, 1, 'successful lists should be cached');
    } else {
        assert.equal(writes.length, 0, 'failed responses must not enter cache');
        assert.equal(rendered.length, 0, 'failed responses must not render as lists');
        const container = ['loadPlaylists', 'loadArtists'].includes(name) ? playlists : tracks;
        assert.equal(container.children.length, 1, 'display a safe error element');
        const text = container.children[0].textContent;
        if (['error', 'object-error'].includes(scenario)) assert.ok(text.includes(message), text);
        else assert.ok(text.length > 0);
        assert.ok(!container.innerHTML.includes(message), 'server text must not be interpolated into HTML');
        await ctx[name]('id', element());
        assert.equal(requests, 2, 'failures must remain retryable');
    }
})().catch(error => {console.error(error); process.exitCode = 1;});
'''
    result = subprocess.run(['node', '-e', script, str(APP), name, scenario],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


class BrowseErrorTests(unittest.TestCase):
    def test_server_errors_are_safe_visible_and_not_cached(self):
        for name in LOADERS:
            with self.subTest(loader=name):
                run_loader(name, 'error')


    def test_response_validation_and_successful_cache(self):
        for name in LOADERS:
            for scenario in ['object-error', 'malformed', 'http-array', 'invalid-json', 'success', 'empty']:
                with self.subTest(loader=name, scenario=scenario):
                    run_loader(name, scenario)

    def test_browse_loading_labels_are_translated(self):
        source = APP.read_text()
        for label in ['Top Nummers', 'Top nummers laden...', 'Nummers laden...', 'Artiesten laden...']:
            self.assertNotIn(label, source)


if __name__ == '__main__':
    unittest.main()
