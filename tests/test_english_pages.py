"""Stdlib checks for the English startup and first-run pages."""
from pathlib import Path
import re
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class EnglishPagesTests(unittest.TestCase):
    def test_loader_english_copy(self):
        page = (ROOT / 'static/loader.html').read_text()
        for text in ('<html lang="en">', 'Loading - Spotify Kiosk Player',
                     '>Spotify Kiosk Player<', 'Starting...', 'Loading services...',
                     'Almost ready...', 'Please wait...', 'Ready!', 'Something went wrong',
                     'Spotify Kiosk Player could not start.',
                     'Try again or restart the device.', '>Try again</button>'):
            with self.subTest(text=text):
                self.assertIn(text, page)
        for text in ('Opstarten', 'Muziekspeler', 'Opnieuw', 'Gereed', 'geduld'):
            self.assertNotIn(text, page)

    def test_setup_english_instructions_match_installer(self):
        page = (ROOT / 'templates/setup.html').read_text()
        for text in ('<html lang="en">', 'Setup - Spotify Kiosk Player',
                     'Welcome to Spotify Kiosk Player', 'Get Your Client ID and Secret',
                     'Create the .env File', 'Restart the Server', 'Refresh Page',
                     'Need help?', 'your_client_id_here', 'your_client_secret_here',
                     'a_random_string_here'):
            with self.subTest(text=text):
                self.assertIn(text, page)
        self.assertNotIn('localhost', page)
        self.assertNotIn('Kids Spotify Player', page)
        self.assertEqual(page.count('http://127.0.0.1:5000/callback'), 3)
        self.assertIn('SPOTIFY_REDIRECT_URI=http://127.0.0.1:5000/callback',
                      (ROOT / 'install.sh').read_text())

    def test_login_english_copy_preserves_login_action(self):
        page = (ROOT / 'templates/login_required.html').read_text()
        for text in ('<html lang="en">', 'Login - Spotify Kiosk Player',
                     '>Spotify Kiosk Player</h1>',
                     'Log in with your Spotify account to continue',
                     'Log in with Spotify', 'Please wait, redirecting you to Spotify...',
                     'You need a Spotify Premium account to play music.',
                     'After logging in, you can access your playlists.',
                     'href="/login"', 'onclick="showLoading()"'):
            with self.subTest(text=text):
                self.assertIn(text, page)
        self.assertNotIn('Kids Spotify Player', page)

    @unittest.skipUnless(shutil.which('node'), 'Node.js is not installed')
    def test_loader_runtime_success_failure_and_retry(self):
        match = re.search(r'<script>(.*?)</script>',
                          (ROOT / 'static/loader.html').read_text(), re.S)
        assert match is not None, 'Loader script is missing'
        script = match.group(1)
        harness = r"""
const vm = require('node:vm');
const assert = require('node:assert/strict');
const script = JSON.parse(process.argv[1]);
async function run(healthy) {
    const elements = {};
    const timers = new Map();
    const requests = [];
    let nextId = 0;
    let start;
    const context = vm.createContext({
        document: {
            getElementById(id) { return elements[id] ||= {style: {}, textContent: ''}; },
            addEventListener(event, fn) { assert.equal(event, 'DOMContentLoaded'); start = fn; }
        },
        window: {location: {href: ''}}, AbortController,
        console: {log() {}},
        setTimeout(fn, delay) { timers.set(++nextId, {fn, delay}); return nextId; },
        clearTimeout(id) { timers.delete(id); },
        async fetch(url, options) {
            requests.push({url, options});
            if (!healthy) throw new Error('offline');
            return {ok: true, async json() { return {status: 'ok'}; }};
        }
    });
    vm.runInContext(script, context);
    const flush = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };
    const fire = async delay => {
        const entry = [...timers].find(([, timer]) => timer.delay === delay);
        assert.ok(entry, `Missing ${delay}ms timer`);
        timers.delete(entry[0]); entry[1].fn(); await flush();
    };
    start(); await flush();
    assert.equal(requests[0].url, 'http://127.0.0.1:5000/api/health');
    assert.equal(requests[0].options.cache, 'no-store');
    assert.equal(requests[0].options.method, 'GET');
    if (healthy) {
        assert.equal(elements['status-text'].textContent, 'Ready!');
        assert.equal(elements['progress-bar'].style.width, '100%');
        await fire(300);
        assert.equal(context.window.location.href, 'http://127.0.0.1:5000/');
    } else {
        assert.equal(elements['status-text'].textContent, 'Starting...');
        for (let attempt = 2; attempt <= 120; attempt++) {
            await fire(500);
            if (attempt === 10) assert.equal(elements['status-text'].textContent, 'Loading services...');
            if (attempt === 40) assert.equal(elements['status-text'].textContent, 'Almost ready...');
            if (attempt === 80) assert.equal(elements['status-text'].textContent, 'Please wait...');
        }
        assert.equal(requests.length, 120);
        assert.equal(elements['loading-state'].style.display, 'none');
        assert.equal(elements['error-state'].style.display, 'block');
        assert.ok(![...timers.values()].some(timer => timer.delay === 500));
        assert.equal(context.window.location.href, '');
        healthy = true;
        context.startHealthCheck(); await flush();
        assert.equal(elements['loading-state'].style.display, 'block');
        assert.equal(elements['error-state'].style.display, 'none');
        assert.equal(elements['status-text'].textContent, 'Ready!');
        await fire(300);
        assert.equal(context.window.location.href, 'http://127.0.0.1:5000/');
    }
}
(async () => { await run(true); await run(false); })().catch(error => {
    console.error(error); process.exitCode = 1;
});
"""
        import json
        result = subprocess.run(['node', '-e', harness, json.dumps(script)],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
