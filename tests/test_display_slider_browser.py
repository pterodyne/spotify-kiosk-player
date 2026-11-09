"""Optional Chromium integration: actual frontend functions and Flask route, no Pi I/O."""
import json
from pathlib import Path
import threading

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_browser_slider_posts_all_stops(tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    from flask import Flask, session
    from werkzeug.serving import make_server
    import display_timeout as d
    app = Flask(__name__)
    app.secret_key = 'browser-test'
    path = tmp_path / 'display.json'
    path.write_text('{"minutes":5}')
    app.config['DISPLAY_TIMEOUT_PATH'] = path
    d.register_display_routes(app)

    @app.before_request
    def authenticated_fixture():
        session['token_info'] = {'access_token': 'fixture-only'}

    html = (ROOT / 'templates/index.html').read_text()
    markup = html[html.index('<div class="display-timeout-setting">'):html.index('<hr class="other-divider">')]
    source = (ROOT / 'static/js/app.js').read_text()
    source = source[source.index('const SCREEN_TIMEOUT_SECONDS'):source.index('// ACCOUNT FUNCTIONALITY')]

    @app.get('/')
    def fixture():
        return '<html><body style="background:#222;color:white">' + markup + '<script>function showToast(){}; function t(x){return x;}' + source + 'setupScreenTimeout();loadScreenTimeout();</script></body></html>'

    server = make_server('127.0.0.1', 5000, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with playwright.sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 800, 'height': 480})
            page.goto('http://127.0.0.1:5000/')
            slider = page.locator('#screen-timeout-slider')
            page.wait_for_function('!document.querySelector("input").disabled')
            assert slider.input_value() == '3'
            assert json.loads(path.read_text()) == {'minutes': 5}
            for index, seconds, label in [(0, 0, 'Never'), (1, 30, '30 sec'), (2, 60, '1 min'), (3, 300, '5 min'), (4, 1800, '30 min')]:
                with page.expect_response(lambda r: r.request.method == 'POST') as response:
                    box = slider.bounding_box()
                    slider.click(position={'x': 8 + (box['width'] - 16) * index / 4, 'y': box['height'] / 2})
                assert response.value.status == 200
                assert response.value.request.post_data_json == {'seconds': seconds}
                page.wait_for_function('!document.querySelector("input").disabled')
                assert page.locator('#screen-timeout-value').inner_text() == label
                assert json.loads(path.read_text()) == {'seconds': seconds}
                assert page.request.get('http://127.0.0.1:5000/api/system/screen-timeout?unit=seconds').json() == {'seconds': seconds}
            assert slider.bounding_box()['height'] >= 44
            browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)
