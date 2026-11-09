"""Standalone keyboard setup tests: all writes and command stubs are isolated."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/setup-keyboard.sh'


class KeyboardSetupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.config = self.home / '.config/sway/config'
        self.config.parent.mkdir(parents=True)
        self.original = 'output DSI-1 transform 270\nexec chromium --kiosk --ozone-platform=wayland\n'
        self.config.write_text(self.original)
        self.bin = self.home / 'bin'
        self.bin.mkdir()
        self.env = dict(os.environ, HOME=str(self.home), PATH=f'{self.bin}:/usr/bin:/bin', XDG_CONFIG_HOME=str(self.home / '.config'))
        self.stub('sudo', 'exit 99')
        self.stub('apt-get', 'exit 99')
        self.stub('wvkbd-mobintl', 'exit 99')

    def stub(self, name, body):
        file = self.bin / name
        file.write_text('#!/bin/sh\n' + body + '\n')
        file.chmod(0o755)

    def run_setup(self, *args):
        return subprocess.run(['bash', str(SCRIPT), *args], env=self.env, text=True, capture_output=True)

    def test_configure_preserves_config_and_is_idempotent(self):
        result = self.run_setup()
        self.assertEqual(result.returncode, 0, result.stderr)
        configured = self.config.read_text()
        self.assertTrue(configured.startswith(self.original))
        self.assertIn('exec wvkbd-mobintl --hidden', configured)
        self.assertIn('bindsym Mod4+Ctrl+k exec pkill -RTMIN -u "$(id -u)" -x wvkbd-mobintl', configured)
        backups = list(self.config.parent.glob('config.keyboard-backup.*'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), self.original)
        result = self.run_setup()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.config.read_text(), configured)
        self.assertEqual(list(self.config.parent.glob('config.keyboard-backup.*')), backups)

    def test_help_and_dry_run_do_not_write(self):
        self.assertEqual(self.run_setup('--help').returncode, 0)
        result = self.run_setup('--dry-run')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--hidden', result.stdout)
        self.assertEqual(self.config.read_text(), self.original)
        self.assertEqual(list(self.config.parent.glob('config.keyboard-backup.*')), [])

    def test_unavailable_apt_candidate_fails_without_changes(self):
        self.stub('apt-cache', "printf 'wvkbd:\\n  Candidate: (none)\\n'")
        result = self.run_setup('--install')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('candidate', result.stderr.lower())
        self.assertEqual(self.config.read_text(), self.original)

    def test_install_requires_explicit_confirmation_flag(self):
        self.stub('apt-cache', "printf 'wvkbd:\\n  Candidate: 0.14\\n'")
        result = self.run_setup('--install')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('--yes', result.stderr)
        self.assertEqual(self.config.read_text(), self.original)

    def test_malformed_markers_are_not_overwritten(self):
        broken = self.original + '# BEGIN spotify-kiosk optional wvkbd\n'
        self.config.write_text(broken)
        result = self.run_setup()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.config.read_text(), broken)


if __name__ == '__main__':
    unittest.main()
