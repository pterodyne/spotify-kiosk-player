"""Offline Chromium checks for the self-contained kiosk boot screen.

Optional dependencies: pytest, playwright, and `playwright install chromium`.
"""
from pathlib import Path
import unittest

try:
    import pytest
except ImportError:
    raise unittest.SkipTest('Optional boot screen tests require pytest and playwright')

playwright = pytest.importorskip('playwright.sync_api')
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def page():
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        requests = []
        page.on('request', lambda request: requests.append(request.url))
        page.route('**/*', lambda route: route.fulfill(status=503, body='offline'))
        page.set_content((ROOT / 'static/loader.html').read_text())
        yield page, requests
        browser.close()


@pytest.mark.parametrize('width,height', [(720, 720), (720, 470), (320, 320)])
def test_branded_boot_fits_without_network_assets(page, width, height):
    page, requests = page
    page.set_viewport_size({'width': width, 'height': height})
    assert page.get_by_role('heading', name='Player', exact=True).is_visible()
    logo = page.get_by_role('img', name='Spotify', exact=True)
    assert logo.is_visible()
    assert logo.evaluate('(el) => el.tagName.toLowerCase()') == 'svg'
    assert logo.evaluate('(el) => getComputedStyle(el).color') == 'rgb(30, 215, 96)'
    assert logo.bounding_box()['y'] + logo.bounding_box()['height'] < page.get_by_role('heading', name='Player', exact=True).bounding_box()['y']
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth && document.documentElement.scrollHeight <= innerHeight')
    assert page.locator('#status-text').get_attribute('role') == 'status'
    assert page.locator('#progress-bar').count() == 1
    assert page.evaluate("getComputedStyle(document.body).backgroundColor") == 'rgb(9, 11, 10)'
    assert page.evaluate("document.getAnimations().some(a => a.playState === 'running')")
    assert logo.evaluate('(el) => el.getAnimations().length') == 0
    assert all(url == 'http://127.0.0.1:5000/api/health' for url in requests)


def test_reduced_motion_and_error_state_fit(page):
    page, _ = page
    page.emulate_media(reduced_motion='reduce')
    assert page.evaluate("document.getAnimations().every(a => a.playState !== 'running')")
    page.set_viewport_size({'width': 320, 'height': 320})
    page.evaluate('showError()')
    assert page.get_by_role('heading', name='Something went wrong').is_visible()
    button = page.get_by_role('button', name='Try again')
    assert button.bounding_box()['height'] >= 44
    button.focus()
    assert button.evaluate('(el) => getComputedStyle(el).outlineStyle') != 'none'
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth && document.documentElement.scrollHeight <= innerHeight')
    button.click()
    assert page.locator('#loading-state').is_visible()
    assert not page.locator('#error-state').is_visible()
