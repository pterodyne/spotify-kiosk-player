#!/usr/bin/env bash
# Explicit opt-in only. Never called by the application installer.
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
SOURCE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../plymouth/spotify-player" && pwd)
exec python3 - "$SOURCE" "$@" <<'PY'
import argparse
import datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

parser = argparse.ArgumentParser(description='Install or restore the Linux Plymouth boot theme (never reboots).')
mode = parser.add_mutually_exclusive_group(required=True)
mode.add_argument('--dry-run', action='store_true')
mode.add_argument('--install', action='store_true')
mode.add_argument('--rollback', metavar='BACKUP_DIRECTORY')
parser.add_argument('--root', default='/', help='Alternate fixture root: dry-run only')
args = parser.parse_args(sys.argv[2:])
source = Path(sys.argv[1])
root = Path(args.root).resolve()
if root != Path('/') and not args.dry_run:
    parser.error('--root is supported only with --dry-run')
if not args.dry_run and os.geteuid() != 0:
    parser.error('Run explicitly with sudo for --install or --rollback')

def target(path):
    return root / path.lstrip('/')

FIXED_PATHS = {'boot/firmware/cmdline.txt', 'boot/firmware/config.txt',
               'etc/plymouth/plymouthd.conf', 'usr/share/plymouth/themes/default.plymouth',
               'etc/alternatives/default.plymouth', 'usr/share/plymouth/themes/spotify-player',
               'boot/firmware/initramfs8', 'boot/firmware/initramfs_2712'}


def allowed(rel):
    return (isinstance(rel, str) and not rel.startswith('/') and
            '..' not in rel.split('/') and
            (rel in FIXED_PATHS or re.fullmatch(r'boot/initrd[.]img-[A-Za-z0-9_.+~-]+', rel) or
             re.fullmatch(r'boot/firmware/initramfs[A-Za-z0-9_.+~-]*', rel)))


def trusted(path):
    info = path.lstat()
    if info.st_uid != 0 or (not path.is_symlink() and info.st_mode & 0o022):
        parser.error('Backup must be root-owned and not group/world writable: ' + str(path))
    return info


if args.rollback:
    import stat
    import tempfile
    backup = Path(os.path.abspath(args.rollback))
    # Refuse symlinked or writable backup ancestors before reading any input.
    for parent in [backup, *backup.parents]:
        trusted(parent)
        if parent.is_symlink() or not parent.is_dir():
            parser.error('Untrusted backup directory: ' + str(parent))
    if backup.stat().st_mode & 0o077:
        parser.error('Backup directory must have private mode 0700')
    manifest_path = backup / 'manifest.json'
    trusted(manifest_path)
    if manifest_path.is_symlink() or not manifest_path.is_file():
        parser.error('Manifest must be a regular file')
    manifest = json.loads(manifest_path.read_text())
    if not isinstance(manifest, dict) or not manifest:
        parser.error('Manifest must be a nonempty dictionary of booleans')
    # Validate the ENTIRE restore plan before deleting or replacing anything.
    for rel, existed in manifest.items():
        if not allowed(rel) or type(existed) is not bool:
            parser.error('Invalid manifest entry: ' + repr(rel))
        dest = target(rel)
        for parent in dest.parents:
            if parent.is_symlink():
                parser.error('Symlinked destination parent: ' + str(parent))
        if existed:
            saved = backup / 'files' / rel
            for parent in [saved.parent, *saved.parent.parents]:
                if parent == backup:
                    break
                trusted(parent)
                if parent.is_symlink() or not parent.is_dir():
                    parser.error('Invalid snapshot parent: ' + str(parent))
            trusted(saved)  # Missing snapshots fail here, before any mutation.
            objects = [saved, *saved.rglob('*')] if saved.is_dir() and not saved.is_symlink() else [saved]
            for obj in objects:
                info = trusted(obj)
                if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)):
                    parser.error('Unsupported snapshot object: ' + str(obj))
                if obj.is_symlink() and rel not in {'usr/share/plymouth/themes/default.plymouth', 'etc/alternatives/default.plymouth'}:
                    parser.error('Unexpected snapshot symlink: ' + str(obj))
            if saved.is_dir() and rel != 'usr/share/plymouth/themes/spotify-player':
                parser.error('Unexpected snapshot directory: ' + rel)
        if dest.is_dir() and not dest.is_symlink() and rel != 'usr/share/plymouth/themes/spotify-player':
            parser.error('Unexpected destination directory: ' + rel)
    for rel, existed in manifest.items():
        dest = target(rel)
        saved = backup / 'files' / rel
        if existed and saved.is_file() and not saved.is_symlink():
            # Keep the original present until a fully copied replacement is ready.
            dest.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix='.' + dest.name + '.', dir=dest.parent)
            os.close(fd)
            try:
                shutil.copy2(saved, temporary)
                os.replace(temporary, dest)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            continue
        if dest.is_dir() and not dest.is_symlink():
            shutil.rmtree(dest)
        elif dest.exists() or dest.is_symlink():
            dest.unlink()
        if existed:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if saved.is_dir() and not saved.is_symlink():
                shutil.copytree(saved, dest, symlinks=True)
            else:
                shutil.copy2(saved, dest, follow_symlinks=False)
    print('Restored exact configuration, theme selection, and saved boot images. No reboot performed.')
    sys.exit(0)

cmdline = target('/boot/firmware/cmdline.txt')
firmware = target('/boot/firmware/config.txt')
original = cmdline.read_text()
if len(original.splitlines()) != 1 or not original.strip():
    parser.error('cmdline.txt must contain exactly one non-empty line')
configuration = firmware.read_text()
# Fail closed rather than guessing conditional/include-driven firmware filenames.
section = 'all'
for line in configuration.splitlines():
    directive = line.split('#', 1)[0].strip()
    if directive.startswith('[') and directive.endswith(']'):
        section = directive[1:-1]
    if (re.match(r'(?i)^(kernel|initramfs|include|os_prefix|ramfsfile|ramfsaddr)\b', directive) or
            (re.match(r'^arm_64bit\s*=', directive) and not re.fullmatch(r'arm_64bit\s*=\s*1', directive)) or
            (re.match(r'^auto_initramfs\s*=', directive) and (section != 'all' or not re.fullmatch(r'auto_initramfs\s*=\s*1', directive)))):
        parser.error('Unsupported firmware directive; establish actual loaded image manually: ' + directive)
if not re.search(r'^\s*auto_initramfs\s*=\s*1\s*$', configuration, re.M):
    parser.error('Expected existing auto_initramfs=1; inspect firmware configuration manually')
# Read-only hook inspection: unknown/dynamic layouts require manual review, not a guess.
hook_dir = target('/etc/initramfs/post-update.d')
hooks = sorted(p for p in hook_dir.glob('*') if p.is_file() and os.access(p, os.X_OK))
import hashlib
# Byte-for-byte reviewed target hook; fixture records provenance. Do not infer
# shell behavior from output-name substrings (the real hook builds names).
reviewed_sha256 = '827fb7253c8cdcba0d3530fb8ed0d116ccc214cf9c97201c60dca46901c60ec3'
reviewed = len(hooks) == 1 and hashlib.sha256(hooks[0].read_bytes()).hexdigest() == reviewed_sha256
if reviewed:
    # Never source shell configuration during preflight. Only this deliberately
    # small literal grammar preserves the reviewed hook's behavior.
    defaults = target('/etc/default/raspi-firmware')
    if defaults.exists():
        for line in defaults.read_text().splitlines():
            directive = line.strip()
            if directive and not directive.startswith('#') and not re.fullmatch(r'''INITRAMFS=(?:auto|'auto'|"auto")\s*(?:#.*)?''', directive):
                parser.error('Unsupported raspi-firmware defaults; require literal INITRAMFS=auto only: ' + directive)
    if os.environ.get('INITRAMFS', 'auto') != 'auto' or os.environ.get('DEB_MAINT_PARAMS', ''):
        parser.error('Unsupported inherited INITRAMFS or DEB_MAINT_PARAMS')
    versions = {p.name for p in target('/lib/modules').glob('*') if p.is_dir()}
    versions.update(p.name[len('initrd.img-'):] for p in target('/boot').glob('initrd.img-*'))
    if not versions or any(not re.fullmatch(r'[A-Za-z0-9_.+~-]+-rpi-(?:v8|2712)', version) for version in versions):
        parser.error('Unsupported installed kernel flavours; reviewed outputs cover only rpi-v8 and rpi-2712')
    print('Accepted reviewed SHA256 raspi-firmware hook: ' + reviewed_sha256)
    print('Reviewed installed kernels: ' + ', '.join(sorted(versions)))
else:
    # Retain the simple literal-copy fixture/layout without accepting arbitrary
    # shell programs merely because they mention the expected filenames.
    literal_hook = b'#!/bin/sh\ncp "$2" /boot/firmware/initramfs8\ncp "$2" /boot/firmware/initramfs_2712\n'
    if len(hooks) != 1 or hooks[0].read_bytes() != literal_hook:
        parser.error('Cannot establish firmware outputs initramfs8 and initramfs_2712 from executable post-update hooks; inspect target hooks manually')
print('Inspected executable initramfs post-update hooks: ' + ', '.join(str(p) for p in hooks))
print('Expected firmware outputs: /boot/firmware/initramfs8 /boot/firmware/initramfs_2712')
tokens = original.split()
extra = [token for token in ('quiet', 'splash', 'plymouth.ignore-serial-consoles') if token not in tokens]
new_cmdline = original.rstrip('\r\n') + ((' ' + ' '.join(extra)) if extra else '') + '\n'
print('cmdline: ' + new_cmdline.strip())
print('Theme: spotify-player; firmware config/overlays and console/root tokens unchanged')
print('Rebuild: update-initramfs -u -k all')
if args.dry_run:
    print('DRY RUN: no files, boot commands, services, or theme selection changed')
    sys.exit(0)
for command in ('update-initramfs', 'plymouth-set-default-theme', 'lsinitramfs'):
    if not shutil.which(command):
        parser.error('Required command missing: ' + command)
if not list(Path('/usr/lib').glob('**/plymouth/script.so')):
    parser.error('Plymouth script plugin is missing')
# Store every potentially rewritten boot image before any boot/config/theme writes.
paths = ['boot/firmware/cmdline.txt', 'boot/firmware/config.txt',
         'etc/plymouth/plymouthd.conf', 'usr/share/plymouth/themes/default.plymouth',
         'etc/alternatives/default.plymouth', 'usr/share/plymouth/themes/spotify-player',
         'boot/firmware/initramfs8', 'boot/firmware/initramfs_2712']
paths += [str(p.relative_to('/')) for p in Path('/boot').glob('initrd.img-*')]
paths += [str(p.relative_to('/')) for p in Path('/boot/firmware').glob('initramfs*')]
paths = list(dict.fromkeys(paths))
size = sum(target(p).stat().st_size for p in paths if target(p).is_file())
if shutil.disk_usage('/var/backups').free < size + 256 * 1024 * 1024:
    parser.error('Insufficient backup space')
if shutil.disk_usage('/boot/firmware').free < 128 * 1024 * 1024:
    parser.error('Need at least 128 MiB free on firmware filesystem for rebuild')
os.umask(0o077)
backup = Path('/var/backups') / ('spotify-player-plymouth-' + datetime.datetime.now().strftime('%Y%m%dT%H%M%S%f'))
backup.mkdir(mode=0o700)
manifest = {}
for rel in paths:
    src = target(rel)
    exists = src.exists() or src.is_symlink()
    manifest[rel] = exists
    if exists:
        dest = backup / 'files' / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir() and not src.is_symlink():
            shutil.copytree(src, dest, symlinks=True)
        else:
            shutil.copy2(src, dest, follow_symlinks=False)
(backup / 'manifest.json').write_text(json.dumps(manifest, indent=2))
selection = subprocess.run(['plymouth-set-default-theme'], check=True, capture_output=True, text=True).stdout
(backup / 'previous-theme.txt').write_text(selection)
print('BACKUP: ' + str(backup), flush=True)
print('On failure restore with: sudo bash scripts/install-boot-splash.sh --rollback ' + str(backup), flush=True)
try:
    dest = target('/usr/share/plymouth/themes/spotify-player')
    dest.mkdir(parents=True, exist_ok=True)
    for name in ('spotify-player.plymouth', 'spotify-player.script', 'logo.png', 'bar.png'):
        shutil.copy2(source / name, dest / name)
    cmdline.write_text(new_cmdline)
    subprocess.run(['plymouth-set-default-theme', 'spotify-player'], check=True)
    subprocess.run(['update-initramfs', '-u', '-k', 'all'], check=True)
    selected = subprocess.run(['plymouth-set-default-theme'], check=True, capture_output=True, text=True).stdout.strip()
    if selected != 'spotify-player':
        raise RuntimeError('Theme readback mismatch: ' + selected)
    images = [Path('/boot/firmware/initramfs8'), Path('/boot/firmware/initramfs_2712')]
    found = False
    for image in images:
        if image.exists():
            listing = subprocess.run(['lsinitramfs', str(image)], check=True, capture_output=True, text=True).stdout
            for name in ('spotify-player.script', 'logo.png', 'bar.png'):
                if 'usr/share/plymouth/themes/spotify-player/' + name not in listing:
                    raise RuntimeError('Missing theme asset in firmware-loaded image: ' + str(image) + ': ' + name)
            found = True
            print('Verified firmware initramfs assets: ' + str(image))
    if not found:
        raise RuntimeError('No firmware-loaded initramfs found; do not reboot')
except Exception:
    print('INSTALL FAILED. Do not reboot; use the rollback command printed above.', file=sys.stderr)
    raise
print('Installed; reboot/display/handoff remain unverified. No reboot performed.')
PY
