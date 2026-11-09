from pathlib import Path
import subprocess

import pytest


@pytest.mark.parametrize('scenario', ['saved_before_load', 'load_during_save', 'stale_load_error', 'newer_load', 'stale_save_error'])
def test_timeout_requests_only_latest_updates_ui(scenario):
    source = (ROOT / 'static/js/app.js').read_text()
    source = source[source.index('const SCREEN_TIMEOUT_SECONDS'):source.index('// ACCOUNT FUNCTIONALITY')]
    harness = r'''
const assert = require('node:assert/strict');
const input = {value: '3', disabled: false, dataset: {}, setAttribute() {},
    addEventListener(name, fn) { this[name] = fn; }};
const status = {textContent: ''};
const label = {textContent: ''};
const document = {getElementById(id) { return id === 'screen-timeout-slider' ? input : id === 'screen-timeout-status' ? status : label; }};
const toasts = [];
const showToast = message => toasts.push(message);
const t = key => key;
const requests = [];
const fetch = (url, options) => new Promise((resolve, reject) => requests.push({url, options, resolve, reject}));
const respond = (n, seconds) => requests[n].resolve({ok: true, json: async () => ({seconds})});
const flush = () => new Promise(resolve => setImmediate(resolve));
'''
    cases = r'''
(async () => {
setupScreenTimeout();
const initial = loadScreenTimeout(); respond(0, 300); await initial;
const scenario = process.argv[1];
if (scenario === 'newer_load') {
    const old = loadScreenTimeout(); const latest = loadScreenTimeout();
    respond(2, 60); await latest; respond(1, 300); await old;
    assert.equal(Number(input.dataset.saved), 60);
    assert.equal(label.textContent, '1 min');
} else if (scenario === 'stale_save_error') {
    input.value = '1'; const old = input.change();
    input.value = '2'; const latest = input.change();
    requests[1].reject(new Error('obsolete save')); await old;
    assert.equal(input.disabled, true);
    assert.equal(status.textContent, 'Saving…');
    assert.deepEqual(toasts, []);
    respond(2, 60); await latest;
    assert.equal(Number(input.dataset.saved), 60);
} else {
    const old = loadScreenTimeout();
    input.value = '1'; const save = input.change();
    if (scenario === 'load_during_save') {
        const duringSave = loadScreenTimeout();
        await flush();
        assert.equal(requests.length, 3, 'do not start loads during a save');
        await duringSave;
        respond(1, 300); await old;
        assert.equal(input.disabled, true, 'stale load must not enable pending save');
        respond(2, 30); await save;
    } else {
        respond(2, 30); await save;
        if (scenario === 'stale_load_error') requests[1].reject(new Error('obsolete load'));
        else respond(1, 300);
        await old;
    }
    assert.equal(Number(input.dataset.saved), 30);
    assert.equal(label.textContent, '30 sec');
    assert.equal(status.textContent, 'Saved. Never keeps the display on.');
    assert.deepEqual(toasts, []);
}
assert.equal(input.disabled, false);
console.log('scenario completed');
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
    result = subprocess.run(['node', '-e', harness + source + cases, scenario], text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'scenario completed' in result.stdout, 'Node exited with an unresolved scenario'


ROOT = Path(__file__).resolve().parents[1]


def test_discrete_slider_markup_and_seconds_transport():
    html = (ROOT / 'templates/index.html').read_text()
    js = (ROOT / 'static/js/app.js').read_text()
    assert 'id="screen-timeout-slider" type="range" min="0" max="4"' in html
    assert 'const SCREEN_TIMEOUT_SECONDS = [0, 30, 60, 300, 1800]' in js
    assert 'JSON.stringify({seconds})' in js
    assert "input.addEventListener('change'" in js
