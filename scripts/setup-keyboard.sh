#!/usr/bin/env bash
# Optional, user-session-only Sway keyboard configuration.
set -euo pipefail
python3 - "$@" <<'PY'
import argparse
import os
from pathlib import Path
import re
import subprocess
import shutil
import sys
import tempfile

config = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'sway/config'
parser = argparse.ArgumentParser(description='Opt-in hidden wvkbd keyboard for an existing Sway kiosk config. Run as the kiosk user, not sudo.')
parser.add_argument('--config', type=Path, default=config, help='existing Sway config path')
parser.add_argument('--dry-run', action='store_true', help='print proposed config; no writes or package installation')
parser.add_argument('--install', action='store_true', help='check apt candidate and optionally install wvkbd')
parser.add_argument('--yes', action='store_true', help='explicitly authorize sudo apt-get install with --install')
args = parser.parse_args()
config = args.config
if args.install:
    if not shutil.which('apt-cache'):
        sys.exit('apt-cache required to check the wvkbd candidate.')
    result = subprocess.run(['apt-cache', 'policy', 'wvkbd'], text=True, capture_output=True, env=dict(os.environ, LC_ALL='C'))
    candidate = re.search(r'^\s*Candidate:\s*(\S+)', result.stdout, re.M)
    if result.returncode or not candidate or candidate[1] == '(none)':
        sys.exit('No apt candidate for wvkbd. Check distribution repositories; optionally run sudo apt update yourself.')
    if not args.yes and not args.dry_run:
        sys.exit('Package installation requires explicit --install --yes authorization.')
    if not args.dry_run:
        subprocess.run(['sudo', 'apt-get', 'install', '-y', '--', 'wvkbd'], check=True)
if not args.dry_run and not shutil.which('wvkbd-mobintl'):
    sys.exit('wvkbd-mobintl missing; use --install --yes or install the wvkbd package yourself.')
if not shutil.which('pkill'):
    sys.exit('pkill missing; install procps yourself.')
if not config.is_file() or config.is_symlink():
    sys.exit('Expected an existing non-symlink Sway config: ' + str(config))
begin = '# BEGIN spotify-kiosk optional wvkbd'
end = '# END spotify-kiosk optional wvkbd'
block = '''# BEGIN spotify-kiosk optional wvkbd
exec wvkbd-mobintl --hidden
bindsym Mod4+Ctrl+k exec pkill -RTMIN -u "$(id -u)" -x wvkbd-mobintl
# END spotify-kiosk optional wvkbd
'''
old = config.read_text()
if begin in old or end in old:
    if old.count(begin) != 1 or old.count(end) != 1 or old.index(begin) >= old.index(end):
        sys.exit('Malformed keyboard markers; repair config manually.')
    start = old.index(begin)
    stop = old.index(end) + len(end)
    if old[stop:stop + 1] == '\n':
        stop += 1
    new = old[:start] + block + old[stop:]
else:
    new = old + ('' if old.endswith('\n') else '\n') + '\n' + block
if args.dry_run:
    print(new, end='')
    sys.exit(0)
if new == old:
    print('Keyboard configuration already up to date.')
    sys.exit(0)
fd, backup = tempfile.mkstemp(prefix='config.keyboard-backup.', dir=config.parent)
os.close(fd)
shutil.copy2(config, backup)
fd, temporary = tempfile.mkstemp(prefix='.keyboard-', dir=config.parent)
try:
    with os.fdopen(fd, 'w') as stream:
        stream.write(new)
    shutil.copymode(config, temporary)
    os.replace(temporary, config)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
print('Updated ' + str(config) + '; backup: ' + backup)
print('Restart your Sway session to start the hidden keyboard. Super+Ctrl+k toggles it.')
PY
