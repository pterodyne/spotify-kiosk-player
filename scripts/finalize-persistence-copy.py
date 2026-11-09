#!/usr/bin/env python3
"""Authoritative copy only. Run a root-owned /root copy via root systemd-run.

Intentionally interrupts networking. Never mounts, stages overlay, or reboots.
The operator must first copy all four trees and close other home writers.
"""
import fcntl
import json
import os
from pathlib import Path
import pwd
import signal
import stat
import subprocess
import sys
import tempfile
import time

UUID = '1f404a93-c5fe-45eb-9cd8-8e8cde1c1a37'
USB = Path('/srv/kiosk-data')
PATHS = ('/home/pterodyne', '/var/lib/bluetooth', '/var/lib/NetworkManager',
         '/etc/NetworkManager/system-connections')
MARKER = USB / '.kiosk-persistence-ready'
USER_PREFIX = ['sudo', '-u', 'pterodyne', '--', 'env', 'XDG_RUNTIME_DIR=/run/user/1000',
               'DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus']
LAUNCHER = '/home/pterodyne/spotify/scripts/launch-player.sh'


def command(args, capture=False):
    return subprocess.run(args, check=True, text=True,
                          stdout=subprocess.PIPE if capture else None).stdout


def real_directory(path):
    for item in (path, *path.parents):
        if not stat.S_ISDIR(item.lstat().st_mode):
            raise RuntimeError('Not a real directory (symlinks forbidden): ' + str(item))


class Operations:
    def preflight(self):
        if os.geteuid() != 0 or pwd.getpwnam('pterodyne').pw_uid != 1000:
            raise RuntimeError('Requires root and kiosk user pterodyne uid 1000')
        real_directory(USB)
        info = USB.lstat()
        if info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o700:
            raise RuntimeError('USB top must be root-owned mode 0700')
        self.check_mount()
        if command(['findmnt', '-n', '-o', 'FSTYPE', '/'], capture=True).strip() == 'overlay':
            raise RuntimeError('Requires non-overlay maintenance boot')
        for source in PATHS:
            real_directory(Path(source))
            real_directory(USB / source.lstrip('/'))
            if os.path.samefile(source, USB / source.lstrip('/')):
                raise RuntimeError('Source is already bound to destination: ' + source)
        runtime = Path('/run/user/1000')
        real_directory(runtime)
        if runtime.stat().st_uid != 1000 or stat.S_IMODE(runtime.stat().st_mode) != 0o700:
            raise RuntimeError('Unsafe kiosk runtime directory')
        sockets = [p for p in runtime.glob('sway-ipc.1000.*.sock')
                   if stat.S_ISSOCK(p.lstat().st_mode) and p.lstat().st_uid == 1000]
        if len(sockets) != 1:
            raise RuntimeError('Expected exactly one real uid1000 Sway IPC socket')
        self.socket = str(sockets[0])
        command(USER_PREFIX + ['swaymsg', '-s', self.socket, '-t', 'get_version'], capture=True)
        if not Path(LAUNCHER).is_file():
            raise RuntimeError('Missing shared app-mode browser launcher')
        # Confirm the user bus responds before intentionally losing SSH/network.
        command(USER_PREFIX + ['systemctl', '--user', 'show-environment'], capture=True)

    def check_mount(self):
        mounts = json.loads(command(['findmnt', '--json', '--mountpoint', str(USB),
                                     '-o', 'UUID,FSTYPE,OPTIONS'], capture=True))['filesystems']
        if len(mounts) != 1 or mounts[0]['uuid'] != UUID or mounts[0]['fstype'] != 'ext4' or 'rw' not in mounts[0]['options'].split(','):
            raise RuntimeError('Approved writable ext4 USB UUID missing')

    def invalidate(self):
        MARKER.unlink(missing_ok=True)

    def active(self, unit, user):
        args = (USER_PREFIX + ['systemctl', '--user']) if user else ['systemctl']
        result = subprocess.run(args + ['is-active', unit], text=True, capture_output=True)
        if result.returncode not in (0, 3):
            raise RuntimeError('Cannot inspect unit: ' + unit)
        return result.returncode == 0

    def stop(self, unit, user):
        command((USER_PREFIX + ['systemctl', '--user'] if user else ['systemctl']) + ['stop', unit])

    def start(self, unit, user):
        command((USER_PREFIX + ['systemctl', '--user'] if user else ['systemctl']) + ['start', unit])

    def browser_running(self):
        result = subprocess.run(['pgrep', '-u', '1000', '-x', 'chromium|chromium-browser'],
                                stdout=subprocess.DEVNULL)
        if result.returncode not in (0, 1):
            raise RuntimeError('Cannot inspect Chromium')
        return result.returncode == 0

    def stop_browser(self):
        # TERM allows profile flush; never SIGKILL a live Chromium profile.
        result = subprocess.run(['pkill', '-TERM', '-u', '1000', '-x', 'chromium|chromium-browser'])
        if result.returncode not in (0, 1):
            raise RuntimeError('Cannot terminate Chromium gracefully')
        deadline = time.monotonic() + 45
        while self.browser_running():
            if time.monotonic() >= deadline:
                raise RuntimeError('Chromium did not exit; refusing authoritative copy')
            time.sleep(0.5)

    def start_browser(self):
        replies = json.loads(command(USER_PREFIX + ['swaymsg', '-s', self.socket, '-t', 'command',
                          'exec ' + LAUNCHER + ' --ozone-platform=wayland --noerrdialogs --disable-infobars'], capture=True))
        if not replies or not all(item.get('success') for item in replies):
            raise RuntimeError('Sway refused shared app-mode launcher')

    def sync(self):
        self.check_mount()
        for source in PATHS:
            command(['rsync', '-aHAXx', '--delete', '--numeric-ids', source,
                     str((USB / source.lstrip('/')).parent) + '/'])

    def compare(self):
        self.check_mount()
        for source in PATHS:
            output = command(['rsync', '-aHAXxnci', '--delete', '--numeric-ids', source,
                              str((USB / source.lstrip('/')).parent) + '/'], capture=True)
            if output:
                # Do not expose profile/cache filenames in public logs.
                raise RuntimeError('Checksum comparison not empty: ' + source)

    def mark(self):
        self.check_mount()
        fd, name = tempfile.mkstemp(prefix='.kiosk-ready-', dir=USB)
        try:
            with os.fdopen(fd, 'w') as handle:
                os.fchmod(handle.fileno(), 0o600)
                os.fchown(handle.fileno(), 0, 0)
                handle.write(UUID + '\n')
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, MARKER)
            directory = os.open(USB, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            Path(name).unlink(missing_ok=True)


def finalize(ops):
    ops.preflight()
    ops.invalidate()
    stopped = []
    browser = False
    try:
        for unit, user in (('NetworkManager.service', False), ('bluetooth.service', False),
                           ('spotify-player.service', True), ('librespot.service', True)):
            if ops.active(unit, user):
                # Record before stop: a failing stop can still have stopped the unit.
                stopped.append((unit, user))
                ops.stop(unit, user)
        browser = ops.browser_running()
        if browser:
            ops.stop_browser()
        ops.sync()
        ops.compare()
        ops.mark()
    except BaseException:
        ops.invalidate()
        raise
    finally:
        errors = []
        # Network first, then Bluetooth, then librespot before its player client.
        for unit, user in sorted(stopped, key=lambda item: (
                'NetworkManager.service', 'bluetooth.service', 'librespot.service',
                'spotify-player.service').index(item[0])):
            try:
                ops.start(unit, user)
            except Exception as exc:
                errors.append(str(exc))
        if browser:
            try:
                ops.start_browser()
            except Exception as exc:
                errors.append(str(exc))
        if errors:
            ops.invalidate()
            raise RuntimeError('Restoration failed; inspect journal: ' + '; '.join(errors))


def main():
    own = Path(__file__).absolute()
    if own.parent != Path('/root') or own.is_symlink() or own.stat().st_uid != 0 or own.stat().st_mode & 0o022:
        raise RuntimeError('Run a root-owned, non-writable, nonsymlink /root copy')
    os.chdir('/root')
    os.umask(0o077)
    # A second copy must not quiesce/restart writers during another final sync.
    with open('/run/kiosk-final-copy.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        def interrupted(signum, frame):
            raise RuntimeError('Interrupted by signal ' + str(signum))
        signal.signal(signal.SIGTERM, interrupted)
        signal.signal(signal.SIGINT, interrupted)
        finalize(Operations())
    print('Final copy checksum-verified; root-private marker written; services restored. No mounts/overlay/reboot performed.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('ERROR: ' + str(exc), file=sys.stderr, flush=True)
        sys.exit(1)
