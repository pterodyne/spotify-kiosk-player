"""Real Chromium UI integration; Spotify endpoints are mocked, never contacted."""
import json
import re
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import pytest

pw = pytest.importorskip('playwright.sync_api')
jinja2 = pytest.importorskip('jinja2')
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def ui():
    with pw.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 720, 'height': 470})
        calls = []
        def route(r):
            path = urlparse(r.request.url).path
            calls.append((path, parse_qs(urlparse(r.request.url).query), r.request.post_data))
            if path.startswith('/static/'):
                f = ROOT / path.lstrip('/')
                return r.fulfill(path=str(f))
            data = [] if path in ['/api/playlists', '/api/artists'] else {}
            if path == '/api/search':
                q = parse_qs(urlparse(r.request.url).query)
                offset = int(q['offset'][0]); kind = q['type'][0]
                data = dict(items=[dict(id=kind + str(offset), name='<img src=x onerror=alert(1)>', artist='Artist', uri='spotify:track:found')], offset=offset, next_offset=20 if offset == 0 else None, type=kind, query=q['q'][0])
            if '/albums' in path or '/tracks' in path:
                data = []
            r.fulfill(json=data)
        page.route('**/*', route)
        template = jinja2.Environment(loader=jinja2.FileSystemLoader(ROOT / 'templates')).get_template('index.html')
        html = template.render(url_for=lambda endpoint, filename: '/static/' + filename)
        page.route('http://kiosk/', lambda r: r.fulfill(body=html, content_type='text/html'))
        page.goto('http://kiosk/')
        yield page, calls
        browser.close()


def test_global_songs_paginate_and_play_without_browse_context(ui):
    page, calls = ui
    search = page.get_by_role('button', name='Search', exact=True).first
    search.click(timeout=1500)
    page.get_by_role('searchbox', name='Search Spotify').fill('outside library')
    page.get_by_role('button', name='Find', exact=True).click()
    result = page.locator('#search-results button')
    pw.expect(result).to_have_count(1)
    assert result.first.inner_text() == '<img src=x onerror=alert(1)> · Artist'
    assert page.locator('#search-results img').count() == 0
    page.get_by_role('button', name='Load More', exact=True).click()
    pw.expect(result).to_have_count(2)
    page.evaluate("currentPlaylistId='old'; currentAlbumId='old-album'")
    result.first.click()
    page.wait_for_timeout(100)
    payload = json.loads(next(c[2] for c in calls if c[0] == '/api/play-track'))
    assert payload == dict(uri='spotify:track:found', playlist_id=None, album_id=None, track_uris=None)
    assert page.evaluate('currentPlaylistId') == 'old'
    assert [c[1]['offset'] for c in calls if c[0] == '/api/search'] == [['0'], ['20']]


@pytest.mark.parametrize('height', [470, 720])
def test_search_touch_layout_keyboard_and_empty_query(ui, height):
    page, calls = ui
    page.set_viewport_size({'width': 720, 'height': height})
    keyboard_requests = []
    page.on('request', lambda request: keyboard_requests.append(request) if urlparse(request.url).path == '/api/keyboard' else None)
    page.get_by_role('button', name='Search', exact=True).click()
    page.wait_for_timeout(100)
    assert keyboard_requests[0].headers.get('origin') == 'http://kiosk'
    assert keyboard_requests[0].headers.get('content-type') == 'application/json'
    assert json.loads(next(c[2] for c in calls if c[0] == '/api/keyboard')) == {'action': 'show'}
    page.get_by_role('button', name='Find', exact=True).click()
    page.wait_for_timeout(50)
    assert len([c for c in calls if c[0] == '/api/keyboard']) == 1
    assert not any(c[0] == '/api/search' for c in calls)
    page.get_by_role('button', name='Hide keyboard', exact=True).click()
    page.wait_for_timeout(50)
    assert json.loads([c[2] for c in calls if c[0] == '/api/keyboard'][-1]) == {'action': 'hide'}
    for selector in ['#open-search', '#search-query', '#search-type', '#hide-search-keyboard', '#close-search']:
        box = page.locator(selector).bounding_box()
        assert box['height'] >= 44 and box['width'] >= 44
        assert box['y'] >= 0 and box['y'] + box['height'] <= height
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


@pytest.mark.parametrize('kind,path', [('artist', '/api/artist/artist0/albums'), ('album', '/api/album/album0/tracks')])
def test_search_opens_existing_browsing(ui, kind, path):
    page, calls = ui
    page.get_by_role('button', name='Search', exact=True).click()
    page.get_by_role('searchbox').fill('new')
    page.get_by_label('Result type').select_option(kind)
    page.get_by_role('button', name='Find', exact=True).click()
    page.locator('#search-results button').click()
    page.wait_for_timeout(100)
    assert any(c[0] == path for c in calls)
    assert page.locator('#tracks-panel').is_visible()
    assert not page.locator('#search-panel').is_visible()


@pytest.mark.parametrize('status,body', [(503, '{"error":"Unavailable"}'), (200, '{"supported":false}'), (200, 'not JSON')])
def test_keyboard_unsupported_keeps_input_usable_without_blur_hide(ui, status, body):
    page, calls = ui
    page.route('**/api/keyboard', lambda r: r.fulfill(status=status, body=body, content_type='application/json'))
    page.get_by_role('button', name='Search', exact=True).click()
    pw.expect(page.locator('#search-status')).to_contain_text('physical keyboard')
    page.get_by_role('searchbox').fill('physical')
    page.get_by_role('button', name='Find', exact=True).click()
    pw.expect(page.locator('#search-results button')).to_have_count(1)
    assert page.get_by_role('searchbox').input_value() == 'physical'


@pytest.mark.parametrize('restore', [False, True])
def test_direct_search_album_has_no_dead_back_and_preserves_playback_context(ui, restore):
    page, calls = ui
    page.route('**/api/album/album0/tracks', lambda r: r.fulfill(json=[dict(
        id='song', name='Song', artist='Artist', album='Album', uri='spotify:track:song', duration_ms=1000)]))
    page.get_by_role('button', name='Search', exact=True).click()
    page.get_by_role('searchbox').fill('album')
    page.get_by_label('Result type').select_option('album')
    page.get_by_role('button', name='Find', exact=True).click()
    page.locator('#search-results button').click()
    pw.expect(page.locator('.album-track-item')).to_have_count(1)
    if restore:
        page.evaluate("loadAlbumTracksById('album0')")
    pw.expect(page.locator('#album-back-btn')).to_be_hidden()
    # Even a programmatic activation must not discard the destination-less context.
    page.locator('#album-back-btn').evaluate('el => el.click()')
    assert page.evaluate('currentAlbumId') == 'album0'
    assert page.evaluate('currentArtistId') is None
    assert 'album=album0' in page.url
    page.locator('.album-play-btn').click()
    page.wait_for_timeout(50)
    page.locator('.album-track-item').click()
    page.wait_for_timeout(50)
    payloads = [json.loads(c[2]) for c in calls if c[0] == '/api/play-track']
    assert len(payloads) == 2
    assert all(p['album_id'] == 'album0' and p['playlist_id'] is None for p in payloads)


def test_debounce_and_search_contrast(ui):
    page, calls = ui
    page.get_by_role('button', name='Search', exact=True).click()
    page.get_by_role('searchbox').fill('a')
    page.wait_for_timeout(100)
    page.get_by_role('searchbox').fill('ab')
    page.wait_for_timeout(100)
    assert not any(c[0] == '/api/search' for c in calls)
    pw.expect(page.locator('#search-results button')).to_have_count(1)
    assert len([c for c in calls if c[0] == '/api/search']) == 1
    for theme in ['light', 'dark']:
        page.evaluate('(theme) => document.body.dataset.theme = theme', theme)
        for selector in ['#open-search', '#search-query', '#search-type', '#hide-search-keyboard', '#search-results button']:
            ratio = page.locator(selector).first.evaluate('''el => {
                const s = getComputedStyle(el);
                const lum = c => c.match(/[\\d.]+/g).slice(0,3).map(Number).map(x => {
                    x /= 255; return x <= .04045 ? x/12.92 : ((x+.055)/1.055)**2.4;
                }).reduce((a,x,i) => a+x*[.2126,.7152,.0722][i],0);
                const a=lum(s.color), b=lum(s.backgroundColor);
                return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);
            }''')
            assert ratio >= 4.5, (theme, selector, ratio)


def test_errors_and_stale_response_guard(ui):
    page, calls = ui
    page.get_by_role('button', name='Search', exact=True).click()
    page.route('**/api/search?**', lambda r: r.fulfill(status=500, json={'error': '<script>secret</script>'}))
    page.get_by_role('searchbox').fill('bad')
    page.get_by_role('button', name='Find', exact=True).click()
    pw.expect(page.locator('#search-status')).to_have_text('Unable to search Spotify. Please try again.')
    page.unroute('**/api/search?**')
    page.evaluate('''() => {
        const original = window.fetch;
        window.fetch = (url, opts) => String(url).includes('/api/search?') && String(url).includes('q=old')
          ? new Promise(resolve => window.finishOldSearch = () => resolve(new Response(JSON.stringify({items:[{name:'STALE'}],next_offset:null}))))
          : original(url, opts);
    }''')
    page.get_by_role('searchbox').fill('old')
    page.get_by_role('button', name='Find', exact=True).click()
    page.get_by_role('searchbox').fill('fresh')
    page.get_by_role('button', name='Find', exact=True).click()
    pw.expect(page.locator('#search-results button')).to_have_count(1)
    page.evaluate('finishOldSearch()')
    page.wait_for_timeout(100)
    assert 'STALE' not in page.locator('#search-results').inner_text()


def test_stale_load_more_cannot_append_to_new_query(ui):
    page, calls = ui
    page.get_by_role('button', name='Search', exact=True).click()
    page.get_by_role('searchbox').fill('old')
    page.get_by_role('button', name='Find', exact=True).click()
    pw.expect(page.locator('#search-results button')).to_have_count(1)
    page.evaluate('''() => {
        const original = window.fetch;
        window.fetch = (url, opts) => String(url).includes('/api/search?') && String(url).includes('offset=20')
          ? new Promise(resolve => window.finishMore = () => resolve(new Response(JSON.stringify({items:[{name:'STALE MORE'}],next_offset:null}))))
          : original(url, opts);
    }''')
    page.get_by_role('button', name='Load More', exact=True).click()
    page.get_by_role('searchbox').fill('fresh')
    page.get_by_role('button', name='Find', exact=True).click()
    pw.expect(page.locator('#search-status')).to_have_text('Spotify results')
    page.evaluate('finishMore()')
    page.wait_for_timeout(100)
    pw.expect(page.locator('#search-results button')).to_have_count(1)
    assert 'STALE MORE' not in page.locator('#search-results').inner_text()
    pw.expect(page.get_by_role('button', name='Load More', exact=True)).to_be_enabled()
    pw.expect(page.get_by_role('button', name='Load More', exact=True)).to_be_visible()
