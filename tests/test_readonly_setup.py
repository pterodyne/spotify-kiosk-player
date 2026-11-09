"""Offline installer tests; never mount or access the Pi."""
import pathlib
import subprocess
import tempfile
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / 'scripts/setup-readonly-root.py'
UUID = '11111111-2222-3333-4444-555555555555'

class ReadonlySetupTests(unittest.TestCase):
    def test_dry_run_generates_fail_closed_plan_without_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / 'etc').mkdir()
            (root / 'etc/fstab').write_text('PARTUUID=sd-01 /boot/firmware vfat defaults 0 2\nPARTUUID=sd-02 / ext4 defaults 0 1\n')
            boot = root / 'boot/firmware'
            boot.mkdir(parents=True)
            (boot / 'cmdline.txt').write_text('root=PARTUUID=sd-02 quiet splash overlayroot=tmpfs\n')
            before = (root / 'etc/fstab').read_text()
            result = subprocess.run(['python3', str(SCRIPT), '--root', tmp, '--uuid', UUID], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('overlayroot=tmpfs:recurse=0', result.stdout)
            self.assertIn('x-systemd.requires-mounts-for=/srv/kiosk-data', result.stdout)
            self.assertIn('/boot/firmware vfat ro', result.stdout)
            self.assertNotIn('nofail', result.stdout)
            self.assertEqual((root / 'etc/fstab').read_text(), before)

    def test_overlay_remount_condition_and_backup_manifest(self):
        import importlib.util
        import json
        from unittest.mock import patch
        spec = importlib.util.spec_from_file_location('readonly_remount', SCRIPT)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        name = 'etc/systemd/system/systemd-remount-fs.service.d/kiosk-overlayroot.conf'
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / 'etc').mkdir()
            (root / 'etc/fstab').write_text('PARTUUID=sd /boot/firmware vfat defaults 0 2\n')
            (root / 'boot/firmware').mkdir(parents=True)
            (root / 'boot/firmware/cmdline.txt').write_text('quiet splash\n')
            files = module.plan(root, UUID)
            self.assertEqual(files.get(name), '[Unit]\nConditionPathIsMountPoint=!/media/root-ro\n')
            # Real systemd evaluates the generated negated condition: a mounted
            # path skips start, an ordinary maintenance directory allows start.
            for path, passes in (('/', False), (tmp, True)):
                result = subprocess.run(['systemd-analyze', 'condition',
                    files[name].splitlines()[1].replace('/media/root-ro', path)],
                    capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, passes, result.stderr)
            real_path = pathlib.Path
            def redirected_path(value):
                return root / 'backups' if value == '/root/kiosk-readonly-backups' else real_path(value)
            with patch.object(module, 'preflight'), patch.object(module, 'Path', side_effect=redirected_path), patch('sys.argv', [str(SCRIPT), '--root', tmp, '--apply']):
                module.main()
            backup = next((root / 'backups').iterdir())
            manifest = json.loads((backup / 'manifest.json').read_text())
            self.assertIn({'path': name, 'existed': False}, manifest)
            self.assertEqual((root / name).read_text(), files[name])
            # No Service/ExecStart override: when the condition passes the
            # vendor remount command and all its existing behavior are retained.
            self.assertNotIn('[Service]', files[name])

    def test_resolver_symlink_plan_apply_and_nondereferencing_backups(self):
        import importlib.util
        import json
        import os
        from unittest.mock import patch
        spec = importlib.util.spec_from_file_location('readonly_dns', SCRIPT)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for original in ('regular', 'symlink', 'dangling', 'absent'):
            with self.subTest(original=original), tempfile.TemporaryDirectory() as tmp:
                root = pathlib.Path(tmp)
                (root / 'etc').mkdir()
                (root / 'etc/fstab').write_text('PARTUUID=sd /boot/firmware vfat defaults 0 2\n')
                (root / 'boot/firmware').mkdir(parents=True)
                (root / 'boot/firmware/cmdline.txt').write_text('quiet splash\n')
                target = root / 'etc/resolv.conf'
                external = root / 'untouched-resolver'
                external.write_text('external must not change\n')
                if original == 'regular':
                    target.write_text('# original\n')
                    target.chmod(0o640)
                elif original in ('symlink', 'dangling'):
                    target.symlink_to(external if original == 'symlink' else root / 'missing')
                old_link = os.readlink(target) if target.is_symlink() else None
                dry = subprocess.run(['python3', str(SCRIPT), '--root', tmp], capture_output=True, text=True)
                self.assertEqual(dry.returncode, 0, dry.stderr)
                self.assertIn('SYMLINK /etc/resolv.conf -> /run/NetworkManager/resolv.conf', dry.stdout)
                self.assertEqual(module.symlink_plan(), {'etc/resolv.conf': '/run/NetworkManager/resolv.conf'})
                self.assertNotIn('etc/resolv.conf', module.plan(root, UUID))
                self.assertEqual(target.is_symlink(), old_link is not None)
                real_path = pathlib.Path
                def redirected_path(value):
                    return root / 'backups' if value == '/root/kiosk-readonly-backups' else real_path(value)
                with patch.object(module, 'preflight'), patch.object(module, 'Path', side_effect=redirected_path), patch('sys.argv', [str(SCRIPT), '--root', tmp, '--apply']):
                    module.main()
                self.assertTrue(target.is_symlink())
                self.assertEqual(os.readlink(target), '/run/NetworkManager/resolv.conf')
                self.assertEqual(external.read_text(), 'external must not change\n')
                backup = next((root / 'backups').iterdir())
                entries = json.loads((backup / 'manifest.json').read_text())
                entry = next(e for e in entries if e['path'] == 'etc/resolv.conf')
                self.assertEqual(entry['existed'], original != 'absent')
                self.assertEqual(entry['type'], 'symlink' if old_link else ('file' if original == 'regular' else 'absent'))
                saved = backup / 'etc/resolv.conf'
                if old_link:
                    self.assertEqual(entry['target'], old_link)
                    self.assertTrue(saved.is_symlink())
                    self.assertEqual(os.readlink(saved), old_link)
                elif original == 'regular':
                    self.assertEqual(saved.read_text(), '# original\n')
                    self.assertEqual(saved.stat().st_mode & 0o777, 0o640)
                else:
                    self.assertFalse(saved.exists())

    def test_rejects_old_exfat_uuid(self):
        result = subprocess.run(['python3', str(SCRIPT), '--uuid', '6AEE-24D4'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Expected ext4 UUID', result.stderr)

    def test_apply_to_fixture_is_rejected_without_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / 'etc').mkdir()
            original = 'PARTUUID=sd-01 /boot/firmware vfat defaults 0 2\n'
            (root / 'etc/fstab').write_text(original)
            boot = root / 'boot/firmware'
            boot.mkdir(parents=True)
            (boot / 'cmdline.txt').write_text('quiet splash\n')
            result = subprocess.run(['python3', str(SCRIPT), '--root', tmp, '--apply'], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('fixtures are dry-run only', result.stderr)
            self.assertEqual((root / 'etc/fstab').read_text(), original)

    def test_display_manager_waits_for_persistent_home(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('readonly_setup', SCRIPT)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / 'etc').mkdir()
            (root / 'etc/fstab').write_text('PARTUUID=sd /boot/firmware vfat defaults 0 2\n')
            (root / 'boot/firmware').mkdir(parents=True)
            (root / 'boot/firmware/cmdline.txt').write_text('quiet splash\n')
            files = module.plan(root, UUID)
            self.assertIn('RequiresMountsFor=/home/pterodyne', files.get('etc/systemd/system/display-manager.service.d/kiosk-persistence.conf', ''))

class PersistenceSecurityTests(unittest.TestCase):
    def test_private_usb_and_marker_metadata(self):
        import importlib.util
        import os
        from unittest.mock import patch
        spec = importlib.util.spec_from_file_location('readonly_security', SCRIPT)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            usb = pathlib.Path(tmp) / 'usb'
            usb.mkdir(mode=0o700)
            marker = usb / '.kiosk-persistence-ready'
            marker.write_text(module.EXPECTED_UUID + '\n')
            marker.chmod(0o600)
            # Exercise real lstat/modes; only ownership is substituted on nonroot hosts.
            real_lstat = pathlib.Path.lstat
            def root_owner(path):
                result = real_lstat(path)
                if os.geteuid() != 0:
                    values = list(result)
                    values[4] = 0
                    return os.stat_result(values)
                return result
            with patch.object(pathlib.Path, 'lstat', root_owner):
                module.check_private_usb(usb, module.EXPECTED_UUID)
                for wrong_owner in (usb, marker):
                    def unowned(path):
                        result = root_owner(path)
                        if path == wrong_owner:
                            values = list(result)
                            values[4] = 1000
                            return os.stat_result(values)
                        return result
                    with patch.object(pathlib.Path, 'lstat', unowned):
                        with self.assertRaises(ValueError):
                            module.check_private_usb(usb, module.EXPECTED_UUID)
                with self.assertRaises(ValueError):
                    module.check_private_usb(usb, UUID)
                linked_parent = pathlib.Path(tmp) / 'linked-parent'
                linked_parent.symlink_to(usb.parent, target_is_directory=True)
                with self.assertRaises(ValueError):
                    module.check_private_usb(linked_parent / 'usb', module.EXPECTED_UUID)
                marker.chmod(0o644)
                with self.assertRaises(ValueError):
                    module.check_private_usb(usb, module.EXPECTED_UUID)
                marker.chmod(0o600)
                usb.chmod(0o755)
                with self.assertRaises(ValueError):
                    module.check_private_usb(usb, module.EXPECTED_UUID)
                usb.chmod(0o700)
                marker.unlink()
                marker.symlink_to('/etc/passwd')
                with self.assertRaises(ValueError):
                    module.check_private_usb(usb, module.EXPECTED_UUID)
                marker.unlink()
                marker.mkdir(mode=0o600)
                with self.assertRaises(ValueError):
                    module.check_private_usb(usb, module.EXPECTED_UUID)
                alias = pathlib.Path(tmp) / 'alias'
                alias.symlink_to(usb, target_is_directory=True)
                with self.assertRaises(ValueError):
                    module.check_private_usb(alias, module.EXPECTED_UUID)

class FinalCopyTests(unittest.TestCase):
    def load_module(self):
        import importlib.util
        path = SCRIPT.with_name('finalize-persistence-copy.py')
        spec = importlib.util.spec_from_file_location('final_copy', path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_final_sync_and_comparison_precede_marker_and_restore_on_failure(self):
        from unittest.mock import Mock, call
        module = self.load_module()
        for failure in (None, 'sync', 'compare', 'stop'):
            with self.subTest(failure=failure):
                ops = Mock()
                ops.active.return_value = True
                ops.browser_running.return_value = True
                if failure:
                    getattr(ops, failure).side_effect = RuntimeError('injected')
                if failure:
                    with self.assertRaises(RuntimeError):
                        module.finalize(ops)
                    ops.mark.assert_not_called()
                else:
                    module.finalize(ops)
                    calls = ops.mock_calls
                    self.assertLess(calls.index(call.stop('NetworkManager.service', False)), calls.index(call.sync()))
                    self.assertLess(calls.index(call.stop('bluetooth.service', False)), calls.index(call.sync()))
                    self.assertLess(calls.index(call.stop_browser()), calls.index(call.sync()))
                    self.assertLess(calls.index(call.sync()), calls.index(call.compare()))
                    self.assertLess(calls.index(call.compare()), calls.index(call.mark()))
                ops.start.assert_any_call('NetworkManager.service', False)
                if failure != 'stop':
                    ops.start.assert_any_call('bluetooth.service', False)
                    ops.start.assert_any_call('spotify-player.service', True)
                    ops.start_browser.assert_called_once()

    def test_exact_mount_uuid_is_required(self):
        import json
        from unittest.mock import patch
        module = self.load_module()
        for uuid in (module.UUID, UUID):
            output = json.dumps({'filesystems': [{'uuid': uuid, 'fstype': 'ext4', 'options': 'rw,nodev,nosuid'}]})
            with patch.object(module, 'command', return_value=output):
                if uuid == module.UUID:
                    module.Operations().check_mount()
                else:
                    with self.assertRaises(RuntimeError):
                        module.Operations().check_mount()

    def test_atomic_private_marker(self):
        import os
        from unittest.mock import patch
        module = self.load_module()
        with tempfile.TemporaryDirectory() as tmp:
            usb = pathlib.Path(tmp)
            marker = usb / '.kiosk-persistence-ready'
            ops = module.Operations()
            ops.check_mount = lambda: None
            with patch.object(module, 'USB', usb), patch.object(module, 'MARKER', marker):
                if os.geteuid() == 0:
                    ops.mark()
                else:
                    with patch.object(module.os, 'fchown'):
                        ops.mark()
                self.assertEqual(marker.read_text(), module.UUID + '\n')
                self.assertEqual(marker.stat().st_mode & 0o777, 0o600)
                self.assertFalse(marker.is_symlink())
                self.assertEqual(list(usb.iterdir()), [marker])

    def test_restoration_attempts_every_service_even_when_start_fails(self):
        from unittest.mock import Mock
        module = self.load_module()
        ops = Mock()
        ops.active.return_value = True
        ops.browser_running.return_value = True
        ops.start.side_effect = RuntimeError('injected restart failure')
        with self.assertRaisesRegex(RuntimeError, 'Restoration failed'):
            module.finalize(ops)
        self.assertEqual(ops.start.call_count, 4)
        ops.start_browser.assert_called_once()
        self.assertEqual(ops.invalidate.call_count, 2)

    def test_comparison_checksums_and_rejects_output_or_failure(self):
        from unittest.mock import patch
        module = self.load_module()
        ops = module.Operations()
        ops.check_mount = lambda: None
        with patch.object(module, 'command', return_value='') as command:
            ops.compare()
            self.assertEqual(command.call_count, 4)
            for args, kwargs in command.call_args_list:
                self.assertIn('-aHAXxnci', args[0])
                self.assertIn('--delete', args[0])
                self.assertTrue(kwargs['capture'])
        with patch.object(module, 'command', return_value='>f changed\n'):
            with self.assertRaises(RuntimeError):
                ops.compare()

if __name__ == '__main__':
    unittest.main()
