from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_display_settings_browser():
    sync_api = pytest.importorskip('playwright.sync_api')
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        source = (ROOT / 'static/js/app.js').read_text()
        start = source.index('function setupScreenTimeout')
        end = source.index('// ============================================', start)
        page.set_content('<input id="screen-timeout-minutes" type="number"><button id="screen-timeout-save">Save</button><button id="screen-timeout-never">Never</button>')
        page.evaluate('''() => {
            window.saved = []; window.failSave = false;
            window.showToast = () => {}; window.t = x => x;
            window.fetch = async (url, options) => {
                if (options) {
                    const body = JSON.parse(options.body); saved.push(body);
                    return {ok: !failSave, json: async () => failSave ? {error:'denied'} : body};
                }
                return {ok:true, json:async()=>({minutes:5})};
            };
        }''')
        page.add_script_tag(content=source[start:end])
        page.evaluate('setupScreenTimeout(); loadScreenTimeout();')
        page.wait_for_function("document.querySelector('input').value === '5'")
        page.fill('input', '17')
        page.click('#screen-timeout-save')
        assert page.evaluate('saved') == [{'minutes': 17}]
        page.click('#screen-timeout-never')
        assert page.evaluate('saved')[-1] == {'minutes': 0}
        page.fill('input', '121')
        page.click('#screen-timeout-save')
        assert len(page.evaluate('saved')) == 2
        page.evaluate('failSave = true')
        page.fill('input', '8')
        page.click('#screen-timeout-save')
        assert page.input_value('input') == '0'
        browser.close()
