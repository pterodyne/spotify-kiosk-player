"""Offline browser layout checks. Optional local deps: pytest playwright jinja2;
run `playwright install chromium` before running this module.
"""
from pathlib import Path
import re

import unittest

try:
    import pytest
except ImportError:
    raise unittest.SkipTest('Optional browser tests require pytest, playwright, and jinja2')

playwright = pytest.importorskip('playwright.sync_api')
jinja2 = pytest.importorskip('jinja2')
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def page():
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={'width': 720, 'height': 720})
        template = jinja2.Environment(loader=jinja2.FileSystemLoader(ROOT / 'templates')).get_template('index.html')
        html = template.render(url_for=lambda endpoint, filename: '/static/' + filename)
        # Exercise the real template, stylesheet and layout script, without Spotify/network.
        html = re.sub(r'<script\b.*?</script>', '', html, flags=re.S)
        html = re.sub(r'<link\b[^>]*>', '', html)
        page.set_content(html)
        page.add_style_tag(path=str(ROOT / 'static/css/styles.css'))
        script = ROOT / 'static/js/layout.js'
        if script.exists():
            page.add_script_tag(path=str(script))
        page.evaluate('''() => {
            document.querySelector('#playlists-container').innerHTML = Array.from({length: 25}, (_, i) =>
              `<button class="${i % 2 ? 'artist-item' : 'playlist-item'}"><span>Representative library item ${i}</span></button>`).join('');
            document.querySelector('#tracks-container').innerHTML = Array.from({length: 40}, (_, i) =>
              `<div class="track-item"><span class="track-name">Representative track ${i}</span></div>`).join('');
            document.querySelector('#track-name').textContent = 'A long representative track title that should truncate';
        }''')
        yield page
        browser.close()


def test_compact_toggle_reuses_left_slot_and_keeps_now_playing(page):
    library = page.get_by_role('button', name='Library', exact=True)
    tracks = page.get_by_role('button', name='Tracks', exact=True)
    assert library.is_visible()
    assert library.get_attribute('aria-pressed') == 'true'
    left = page.locator('.panel-left').bounding_box()
    right = page.locator('.panel-right').bounding_box()
    assert not page.locator('.panel-middle').is_visible()
    assert tracks.bounding_box()['height'] >= 44
    tracks.focus()
    page.keyboard.press('Enter')
    middle = page.locator('.panel-middle').bounding_box()
    assert not page.locator('.panel-left').is_visible()
    assert middle == left
    assert page.locator('.panel-right').bounding_box() == right
    assert tracks.get_attribute('aria-pressed') == 'true'
    library.click()
    assert page.locator('.panel-left').is_visible()


@pytest.mark.parametrize('kind', ['playlist-item', 'artist-item'])
def test_library_selection_automatically_shows_tracks(page, kind):
    page.locator(f'#playlists-container .{kind} span').first.click()
    assert page.locator('.panel-middle').is_visible()
    assert page.get_by_role('button', name='Tracks', exact=True).get_attribute('aria-pressed') == 'true'


@pytest.mark.parametrize('height', [720, 470])
def test_compact_viewport_has_no_overflow_and_controls_fit(page, height):
    page.set_viewport_size({'width': 720, 'height': height})
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert page.evaluate('document.body.getBoundingClientRect().height <= innerHeight')
    for selector in ['.album-art-container', '#btn-previous', '#btn-play-pause', '#btn-next', '#btn-shuffle', '#volume-slider', '#btn-open-settings']:
        box = page.locator(selector).bounding_box()
        assert box['y'] >= 0 and box['y'] + box['height'] <= height, (selector, box)
        assert box['x'] >= 0 and box['x'] + box['width'] <= 720, (selector, box)
    assert page.locator('.panel-right').evaluate('(el) => el.scrollHeight <= el.clientHeight')


@pytest.mark.parametrize('height', [720, 470])
def test_settings_gear_is_compact_lower_right_without_covering_controls(page, height):
    page.set_viewport_size({'width': 720, 'height': height})
    button = page.get_by_role('button', name='Settings', exact=True)
    assert button.is_visible()
    assert button.get_attribute('id') == 'btn-open-settings'
    assert button.get_attribute('title') == 'Settings'
    assert button.get_attribute('data-i18n') == 'control.settings'
    assert button.get_attribute('data-i18n-attr') == 'title'
    box = button.bounding_box()
    pane = page.locator('.panel-right').bounding_box()
    assert 44 <= box['width'] <= 48 and 44 <= box['height'] <= 48
    assert 0 <= pane['x'] + pane['width'] - box['x'] - box['width'] <= 16
    assert 0 <= pane['y'] + pane['height'] - box['y'] - box['height'] <= 16
    for selector in ['#btn-previous', '#btn-play-pause', '#btn-next', '#btn-shuffle', '#volume-slider', '#progress-bar']:
        control = page.locator(selector)
        other = control.bounding_box()
        assert (other['x'] + other['width'] <= box['x'] or box['x'] + box['width'] <= other['x']
                or other['y'] + other['height'] <= box['y'] or box['y'] + box['height'] <= other['y']), selector
        assert control.evaluate('el => { const r = el.getBoundingClientRect(); return el.contains(document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)); }'), selector
    assert button.locator('svg path').count() == 1
    assert button.locator('svg circle').count() == 0
    assert button.locator('svg').get_attribute('aria-hidden') == 'true'
    button.click(trial=True)
    button.focus()
    assert button.evaluate('el => el === document.activeElement')


@pytest.mark.parametrize('height', [720, 470])
def test_settings_fits_viewport_with_scrollable_long_content(page, height):
    page.set_viewport_size({'width': 720, 'height': height})
    page.evaluate('''() => {
        document.querySelector('#settings-modal').classList.remove('hidden');
        document.querySelector('#tab-theme').innerHTML = '<div>' + '<p>Long settings content</p>'.repeat(60) + '</div>';
    }''')
    box = page.locator('.modal-settings').bounding_box()
    assert box['x'] >= 0 and box['x'] + box['width'] <= 720
    assert box['y'] >= 0 and box['y'] + box['height'] <= height
    wrapper = page.locator('.tab-content-wrapper')
    assert wrapper.evaluate('(el) => el.scrollHeight > el.clientHeight')
    wrapper.evaluate('(el) => el.scrollTop = el.scrollHeight')
    assert wrapper.evaluate('(el) => el.scrollTop > 0')
    assert page.locator('.tab-navigation').evaluate('(el) => el.scrollWidth <= el.clientWidth')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


@pytest.mark.parametrize('theme', ['light', 'dark'])
def test_navigation_text_contrast(page, theme):
    page.evaluate('(theme) => document.body.dataset.theme = theme', theme)
    for selected in ['Library', 'Tracks']:
        page.get_by_role('button', name=selected, exact=True).click()
        for name in ['Library', 'Tracks']:
            contrast = page.get_by_role('button', name=name, exact=True).evaluate('''el => {
                const style = getComputedStyle(el);
                const luminance = color => {
                    const rgb = color.match(/[\\d.]+/g).slice(0, 3).map(Number).map(v => {
                        v /= 255; return v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4;
                    });
                    return rgb[0] * .2126 + rgb[1] * .7152 + rgb[2] * .0722;
                };
                const a = luminance(style.color), b = luminance(style.backgroundColor);
                return (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
            }''')
            assert contrast >= 4.5, (theme, name, contrast)


@pytest.mark.parametrize('width', [901, 1280])
def test_wide_screen_keeps_original_three_panes_even_after_resize(page, width):
    page.get_by_role('button', name='Tracks', exact=True).click()
    page.set_viewport_size({'width': width, 'height': 720})
    assert not page.get_by_role('button', name='Library', exact=True).is_visible()
    boxes = [page.locator(selector).bounding_box() for selector in ['.panel-left', '.panel-middle', '.panel-right']]
    assert all(boxes)
    assert boxes[0]['y'] == boxes[1]['y'] == boxes[2]['y']
    assert boxes[0]['x'] + boxes[0]['width'] < boxes[1]['x']
    assert boxes[1]['x'] + boxes[1]['width'] < boxes[2]['x']
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
