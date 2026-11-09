#!/usr/bin/env python3
"""Stage a reversible overlayroot configuration. Dry-run unless --apply.
Never formats, copies live state, mounts, rebuilds initramfs, or reboots.
"""
import argparse
import datetime
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess

EXPECTED_UUID = '1f404a93-c5fe-45eb-9cd8-8e8cde1c1a37'
PATHS = ('/home/pterodyne', '/var/lib/bluetooth', '/var/lib/NetworkManager',
         '/etc/NetworkManager/system-connections')
BEGIN, END = '# BEGIN kiosk persistence', '# END kiosk persistence'


def plan(root, uuid):
    fstab = (root / 'etc/fstab').read_text()
    fstab = re.sub(re.escape(BEGIN) + r'.*?' + re.escape(END) + r'\n?', '', fstab, flags=re.S)
    lines = []
    found_boot = False
    for line in fstab.splitlines():
        fields = line.split()
        if fields and not line.lstrip().startswith('#') and len(fields) >= 4:
            if fields[1] == '/boot/firmware':
                fields[3] = ','.join(['ro'] + [v for v in fields[3].split(',') if v not in ('rw', 'ro', 'defaults')]) .rstrip(',')
                line = ' '.join(fields)
                found_boot = True
            if fields[1] in ('/srv/kiosk-data', *PATHS):
                raise ValueError('Conflicting existing mount: ' + fields[1])
        lines.append(line)
    if not found_boot:
        raise ValueError('Expected /boot/firmware fstab entry missing')
    lines += [BEGIN, f'UUID={uuid} /srv/kiosk-data ext4 defaults,noatime,nodev,nosuid,x-systemd.device-timeout=30s 0 2']
    for path in PATHS:
        lines.append(f'/srv/kiosk-data{path} {path} none bind,x-systemd.requires-mounts-for=/srv/kiosk-data 0 0')
    lines.append(END)
    cmd = (root / 'boot/firmware/cmdline.txt').read_text().split()
    cmd = [arg for arg in cmd if not arg.startswith('overlayroot=')]
    cmd.append('overlayroot=tmpfs:recurse=0')
    result = {'etc/fstab': '\n'.join(lines) + '\n', 'boot/firmware/cmdline.txt': ' '.join(cmd) + '\n'}
    # Prevent network daemons from reading volatile fallback state, including in
    # maintenance mode. RequiresMountsFor adds Requires + After dependencies.
    for service in ('NetworkManager', 'bluetooth'):
        paths = PATHS[2:] if service == 'NetworkManager' else (PATHS[1],)
        result[f'etc/systemd/system/{service}.service.d/kiosk-persistence.conf'] = '[Unit]\nRequiresMountsFor=' + ' '.join(paths) + '\n'
    for service in ('user@1000', 'display-manager'):
        result[f'etc/systemd/system/{service}.service.d/kiosk-persistence.conf'] = '[Unit]\nRequiresMountsFor=/home/pterodyne\n'
    # overlayroot already mounted /; replaying its generated overlay options
    # fails reconfigure. Keep the vendor remount in non-overlay maintenance.
    result['etc/systemd/system/systemd-remount-fs.service.d/kiosk-overlayroot.conf'] = '[Unit]\nConditionPathIsMountPoint=!/media/root-ro\n'
    return result


def check_private_usb(usb, uuid):
    """Reject user-writable attestation storage and link/nonregular markers."""
    for parent in usb.parents:
        if not stat.S_ISDIR(parent.lstat().st_mode):
            raise ValueError('USB path must not traverse symlinks')
    info = usb.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError('USB top must be a real root-owned directory mode 0700')
    marker = usb / '.kiosk-persistence-ready'
    info = marker.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o600:
        raise ValueError('Final-copy marker must be regular root-owned mode 0600 (no symlink)')
    if marker.read_text().strip() != uuid:
        raise ValueError('Final-copy marker missing or mismatched')


def preflight(root, uuid):
    if root != Path('/') or os.geteuid() != 0:
        raise ValueError('--apply requires real root / and uid 0; fixtures are dry-run only')
    if uuid != EXPECTED_UUID:
        raise ValueError('UUID differs from approved formatted USB')
    info = json.loads(subprocess.check_output(['findmnt', '--json', '--mountpoint', '/srv/kiosk-data', '-o', 'UUID,FSTYPE,OPTIONS']))['filesystems'][0]
    if info['uuid'] != uuid or info['fstype'] != 'ext4' or 'rw' not in info['options'].split(','):
        raise ValueError('Expected writable ext4 USB mount missing')
    check_private_usb(root / 'srv/kiosk-data', uuid)
    for path in PATHS:
        src = root / path.lstrip('/')
        dest = root / ('srv/kiosk-data' + path)
        if not src.is_dir() or not dest.is_dir() or src.is_symlink() or dest.is_symlink():
            raise ValueError('Missing directory or unsafe symlink: ' + path)
        if (src.stat().st_uid, src.stat().st_gid, src.stat().st_mode & 0o7777) != (dest.stat().st_uid, dest.stat().st_gid, dest.stat().st_mode & 0o7777):
            raise ValueError('Copy ownership/mode mismatch: ' + path)
    for profile in (root / 'srv/kiosk-data/etc/NetworkManager/system-connections').iterdir():
        if profile.is_file() and (profile.stat().st_uid != 0 or profile.stat().st_mode & 0o077):
            raise ValueError('Network profile must be root-owned and owner-only')
    subprocess.run(['dpkg-query', '-W', '-f=${Status}', 'overlayroot'], check=True, stdout=subprocess.DEVNULL)
    if subprocess.check_output(['findmnt', '-n', '-o', 'FSTYPE', '/'], text=True).strip() == 'overlay':
        raise ValueError('Apply only in non-overlay maintenance mode')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/'))
    parser.add_argument('--uuid', default=EXPECTED_UUID)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', args.uuid):
        parser.error('Expected ext4 UUID, not the old exFAT identifier')
    try:
        files = plan(args.root, args.uuid)
        if not args.apply:
            for path, text in files.items():
                print(f'--- /{path}\n{text}', end='')
            return
        preflight(args.root, args.uuid)
        backup = Path('/root/kiosk-readonly-backups') / datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
        backup.mkdir(parents=True, mode=0o700)
        os.chmod(backup.parent, 0o700)
        manifest = []
        for name in files:
            target = args.root / name
            manifest.append({'path': name, 'existed': target.exists()})
            if target.exists():
                dest = backup / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, dest)
        # Boot archives are copied before the first config write. Root-only:
        # firmware config and Plymouth selection can be needed for recovery.
        for name in ('boot', 'etc/plymouth', 'etc/alternatives/default.plymouth', 'etc/overlayroot.conf', 'etc/overlayroot.local.conf'):
            src = args.root / name
            if src.exists():
                dest = backup / name
                if src.is_dir():
                    shutil.copytree(src, dest, dirs_exist_ok=True, symlinks=True)
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dest, follow_symlinks=False)
        (backup / 'manifest.json').write_text(json.dumps(manifest, indent=2))
        for name, text in files.items():
            target = args.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        print(f'Staged only; no mounts/rebuild/reboot performed. Backup: {backup}')
    except (ValueError, OSError, subprocess.SubprocessError, KeyError, IndexError) as exc:
        parser.exit(1, f'ERROR: {exc}\n')

if __name__ == '__main__':
    main()
