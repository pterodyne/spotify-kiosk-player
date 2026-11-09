"""Real browser coverage for album-only artist browsing, offline."""
import re
from pathlib import Path

import pytest

pw = pytest.importorskip('playwright.sync_api')
jinja2 = pytest.importorskip('jinja2')
ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('cached', [False, True])
@pytest.mark.parametrize('query', ['', '?view=artists&artist=chosen', '?view=artists&artist=chosen&subview=tracks', '?view=artists&artist=chosen&subview=albums', '?view=artists&artist=chosen&album=record'])
def test_artist_navigation_only_requests_albums_and_album_tracks(query, cached):
    source = (ROOT / 'static/js/app.js').read_text()
    functions = '\n'.join(re.findall(r'^(?:async )?function \w+\([^\n]*\) \{[\s\S]*?^\}', source, re.M))
    template = jinja2.Environment(loader=jinja2.FileSystemLoader(ROOT / 'templates')).get_template('index.html')
    html = template.render(url_for=lambda endpoint, filename: '/static/' + filename)
    html = re.sub(r'<script\b.*?</script>', '', html, flags=re.S)
    with pw.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.route('http://kiosk/**', lambda route: route.fulfill(body=html, content_type='text/html'))
        page.goto('http://kiosk/' + query)
        page.evaluate('''() => {
            window.requests = [];
            window.cache = new Map();
            window.currentViewMode = 'artists';
            window.currentArtistId = null; window.currentPlaylistId = null; window.currentAlbumId = null;
            window.currentArtistSubView = 'tracks';
            window.tracksContainer = document.querySelector('#tracks-container');
            window.playlistsContainer = document.querySelector('#playlists-container');
            window.albumBackBtn = document.querySelector('#album-back-btn');
            window.t = key => key;
            window.CACHE_KEYS = {ARTISTS:'artists', ARTIST_ALBUMS_PREFIX:'albums-', ALBUM_TRACKS_PREFIX:'tracks-'};
            window.fetch = async url => {
                requests.push(url);
                const data = url === '/api/artists' ? [{id:'first',name:'First'},{id:'chosen',name:'Chosen'}] :
                    url.endsWith('/albums') ? [{id:'record',name:'Record'}] : [];
                return {ok:true,json:async()=>data};
            };
        }''')
        page.add_script_tag(content=functions)
        page.evaluate('''() => {
            window.getCache = key => cache.get(key);
            window.setCache = (key, data) => cache.set(key, data);
        }''')
        if cached:
            page.evaluate('''() => {
                cache.set('artists', [{id:'first',name:'First'},{id:'chosen',name:'Chosen'}]);
                cache.set('albums-chosen', [{id:'record',name:'Record'}]);
                cache.set('tracks-record', []);
            }''')
        if query:
            page.evaluate('restoreFromURL()')
        else:
            page.evaluate("currentViewMode = 'playlists'; switchViewMode('artists')")
            page.locator('.artist-item').nth(1).click()
        page.wait_for_function("currentArtistId === 'chosen'")
        if 'album=record' not in query:
            page.wait_for_selector('.album-item')
            page.locator('.album-item').click()
        page.wait_for_function("currentAlbumId === 'record'")
        page.evaluate('goBackToAlbums()')
        page.wait_for_selector('.album-item')
        assert page.locator('#tracks-panel-title').inner_text() == 'panel.albums'
        assert page.locator('#album-back-btn').evaluate("el => el.style.display") == 'none'
        assert page.locator('#artist-sub-toggle').count() == 0
        assert page.locator('[data-i18n="panel.topTracks"]').count() == 0
        requests = page.evaluate('requests')
        assert not any('top-tracks' in url for url in requests), requests
        assert requests.count('/api/artist/chosen/albums') == (0 if cached else 1), requests
        assert requests.count('/api/album/record/tracks') == (0 if cached else 1), requests
        assert 'artist=chosen' in page.url and 'album=' not in page.url
        assert 'subview=' not in page.url
        browser.close()
