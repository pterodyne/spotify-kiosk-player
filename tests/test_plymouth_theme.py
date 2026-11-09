"""Boot assets and installer checks; no host boot files are changed."""
import configparser
import pathlib
import struct
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
THEME = ROOT / 'plymouth/spotify-player'
INSTALL = ROOT / 'scripts/install-boot-splash.sh'

class PlymouthThemeTests(unittest.TestCase):
    def fixture_hook(self, directory):
        hook = pathlib.Path(directory) / 'etc/initramfs/post-update.d/fixture'
        hook.parent.mkdir(parents=True)
        hook.write_text('#!/bin/sh\ncp "$2" /boot/firmware/initramfs8\ncp "$2" /boot/firmware/initramfs_2712\n')
        hook.chmod(0o755)

    def test_reviewed_target_hook(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            boot = root / 'boot/firmware'
            boot.mkdir(parents=True)
            (boot / 'cmdline.txt').write_text('root=PARTUUID=abc\n')
            (boot / 'config.txt').write_text('auto_initramfs=1\n')
            self.fixture_hook(directory)
            hook = root / 'etc/initramfs/post-update.d/fixture'
            hook.write_bytes((ROOT / 'tests/fixtures/raspi-firmware/z50-raspi-firmware').read_bytes())
            defaults = root / 'etc/default/raspi-firmware'
            defaults.parent.mkdir(parents=True)
            defaults.write_text('# Target defaults\n#INITRAMFS=auto\n')
            for version in ('6.18.50+rpt-rpi-v8', '6.18.50+rpt-rpi-2712'):
                (root / 'lib/modules' / version).mkdir(parents=True)
                (root / 'boot' / ('initrd.img-' + version)).touch()
            result = subprocess.run(['bash', str(INSTALL), '--dry-run', '--root', directory], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('reviewed SHA256', result.stdout)
            command = ['bash', str(INSTALL), '--dry-run', '--root', directory]
            for content in ('INITRAMFS=no\n', 'INITRAMFS=$(touch /tmp/unsafe)\n', 'firmware_dst=/elsewhere\n', 'KERNEL=auto; false\n'):
                with self.subTest(defaults=content):
                    defaults.write_text(content)
                    result = subprocess.run(command, capture_output=True, text=True)
                    self.assertNotEqual(result.returncode, 0, result.stdout)
            defaults.write_text('INITRAMFS=auto\n')
            extra = hook.parent / 'unexpected'
            extra.write_text('#!/bin/sh\n# /boot/firmware initramfs8 initramfs_2712\nexit 0\n')
            extra.chmod(0o755)
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            extra.unlink()
            unsupported = root / 'lib/modules/6.1-rpi-v8-rt'
            unsupported.mkdir()
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            unsupported.rmdir()
            hook.write_bytes(hook.read_bytes() + b'\n# initramfs8 initramfs_2712 /boot/firmware\n')
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)

    def test_assets_and_callbacks(self):
        self.assertTrue((THEME / 'spotify-player.plymouth').is_file())
        cfg = configparser.ConfigParser()
        cfg.read(THEME / 'spotify-player.plymouth')
        self.assertEqual(cfg['Plymouth Theme']['ModuleName'], 'script')
        for name, size in [('logo.png', (360, 280)), ('bar.png', (120, 4))]:
            data = (THEME / name).read_bytes()
            self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n')
            self.assertEqual(struct.unpack('>II', data[16:24]), size)
        script = (THEME / 'spotify-player.script').read_text()
        for callback in ['Refresh', 'DisplayPassword', 'DisplayQuestion', 'DisplayNormal', 'Message', 'HideMessage']:
            self.assertIn('Plymouth.Set' + callback + 'Function', script)
        self.assertIn('Math.Sin', script)

    def test_native_plymouth_parser(self):
        import ctypes
        import glob
        plugins = glob.glob('/usr/lib/*/plymouth/script.so')
        if not plugins:
            self.skipTest('Plymouth script plugin unavailable')
        library = ctypes.CDLL(plugins[0])
        library.script_parse_file.argtypes = [ctypes.c_char_p]
        library.script_parse_file.restype = ctypes.c_void_p
        library.script_parse_op_free.argtypes = [ctypes.c_void_p]
        tree = library.script_parse_file(str(THEME / 'spotify-player.script').encode())
        self.assertTrue(tree, 'Native Plymouth parser rejected theme')
        library.script_parse_op_free(tree)

    def test_requires_explicit_mode(self):
        result = subprocess.run(['bash', str(INSTALL)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)

    def test_rejects_ambiguous_firmware_before_changes(self):
        for directive in ('kernel=custom.img', 'initramfs custom.img followkernel', 'include other.txt', 'auto_initramfs=0'):
            with self.subTest(directive=directive), tempfile.TemporaryDirectory() as directory:
                root = pathlib.Path(directory)
                boot = root / 'boot/firmware'
                boot.mkdir(parents=True)
                self.fixture_hook(directory)
                (boot / 'cmdline.txt').write_text('root=PARTUUID=abc\n')
                (boot / 'config.txt').write_text('auto_initramfs=1\n' + directive + '\n')
                result = subprocess.run(['bash', str(INSTALL), '--dry-run', '--root', directory], capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0, directive)
                self.assertIn('Unsupported firmware', result.stderr)

    def test_dry_run_deduplicates_tokens_and_rejects_multiline(self):
        with tempfile.TemporaryDirectory() as directory:
            boot = pathlib.Path(directory) / 'boot/firmware'
            boot.mkdir(parents=True)
            self.fixture_hook(directory)
            (boot / 'config.txt').write_text('auto_initramfs=1\n')
            original = 'console=tty1 root=PARTUUID=abc quiet splash plymouth.ignore-serial-consoles\n'
            (boot / 'cmdline.txt').write_text(original)
            command = ['bash', str(INSTALL), '--dry-run', '--root', directory]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('cmdline: ' + original, result.stdout)
            self.assertEqual(result.stdout.count('plymouth.ignore-serial-consoles'), 1)
            (boot / 'cmdline.txt').write_text(original + 'root=wrong\n')
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('exactly one', result.stderr)

    def test_dry_run_preserves_every_file(self):
        self.assertTrue(INSTALL.is_file())
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            boot = root / 'boot/firmware'
            boot.mkdir(parents=True)
            self.fixture_hook(directory)
            (boot / 'cmdline.txt').write_text('console=serial0,115200 console=tty1 root=PARTUUID=abc rootwait\n')
            (boot / 'config.txt').write_text('auto_initramfs=1\ndtoverlay=vc4-kms-dpi-hyperpixel4sq\n')
            before = {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            result = subprocess.run(['bash', str(INSTALL), '--dry-run', '--root', directory], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('quiet splash plymouth.ignore-serial-consoles', result.stdout)
            self.assertIn('update-initramfs -u -k all', result.stdout)
            self.assertEqual(before, {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()})

if __name__ == '__main__':
    unittest.main()
