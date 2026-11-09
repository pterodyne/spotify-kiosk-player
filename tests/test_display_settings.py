from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_display_settings_browser():
    sync_api = pytest.importorskip('playwright.sync_api')
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        source = (ROOT / 'static/js/app.js').read_text()
        start = source.index('const SCREEN_TIMEOUT_SECONDS')
        end = source.index('// ============================================', start)
        page.set_content('<input id="screen-timeout-slider" type="range" min="0" max="4"><output id="screen-timeout-value"></output><p id="screen-timeout-status"></p>')
        page.evaluate('''() => {
            window.saved = []; window.failSave = false;
            window.showToast = () => {}; window.t = x => x;
            window.fetch = async (url, options) => {
                if (options) {
                    const body = JSON.parse(options.body); saved.push(body);
                    return {ok: !failSave, json: async () => failSave ? {error:'denied'} : body};
                }
                return {ok:true, json:async()=>({seconds:300})};
            };
        }''')
        page.add_script_tag(content=source[start:end])
        page.evaluate('setupScreenTimeout(); loadScreenTimeout();')
        page.wait_for_function("document.querySelector('input').value === '3' && !document.querySelector('input').disabled")
        for index, seconds in [(1, 30), (0, 0)]:
            page.locator('input').evaluate('(input, value) => {input.value=value;input.dispatchEvent(new Event("change"));}', index)
            page.wait_for_function('!document.querySelector("input").disabled')
            assert page.evaluate('saved')[-1] == {'seconds': seconds}
        page.evaluate('failSave = true')
        page.locator('input').evaluate('(input) => {input.value=4;input.dispatchEvent(new Event("change"));}')
        page.wait_for_function('!document.querySelector("input").disabled')
        assert page.input_value('input') == '0'
        assert page.locator('#screen-timeout-value').inner_text() == 'Never'
        assert 'Not saved: denied' in page.locator('#screen-timeout-status').inner_text()
        browser.close()
