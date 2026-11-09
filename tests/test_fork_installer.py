import pathlib
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

class ForkInstallerTests(unittest.TestCase):
    def test_noninteractive_error_is_english(self):
        result = subprocess.run(['bash', str(ROOT / 'install.sh')], input='', text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('requires an interactive shell', result.stderr)

    def test_kiosk_launches_borderless_app_without_covering_keyboard(self):
        text = (ROOT / 'install.sh').read_text()
        self.assertNotIn('--kiosk', text)
        self.assertIn('--app=file://${INSTALL_DIR}/static/loader.html', text)

    def test_installer_targets_fork(self):
        text = (ROOT / 'install.sh').read_text()
        self.assertIn('REPO_URL="https://github.com/pterodyne/spotify-kiosk-player.git"', text)
        self.assertNotIn('Kids Spotify Player', text)

if __name__ == '__main__':
    unittest.main()
