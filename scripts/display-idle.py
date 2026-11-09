#!/usr/bin/env python3
"""Run from Sway exec, as the kiosk user; never from the Flask reloader."""
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from display_timeout import config_path, read_seconds


def validate_output(output):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', output):
        raise ValueError('Unsafe output name')
    return output


def discover_output():
    outputs = json.loads(subprocess.check_output(['swaymsg', '-t', 'get_outputs', '-r'], timeout=5))
    connected = [item['name'] for item in outputs if item.get('active')]
    preferred = os.environ.get('KIOSK_DISPLAY_OUTPUT')
    if preferred:
        validate_output(preferred)
        if preferred not in connected:
            raise ValueError('Configured display is not active')
        return preferred
    if 'DPI-1' in connected:
        return 'DPI-1'
    if len(connected) != 1:
        raise ValueError('Set KIOSK_DISPLAY_OUTPUT to one active output')
    return validate_output(connected[0])


def power_on(output):
    subprocess.run(['swaymsg', 'output', validate_output(output), 'power', 'on'], check=True, timeout=5, stdout=subprocess.DEVNULL)


class Supervisor:
    def __init__(self, path, output):
        self.path = path
        self.output = validate_output(output)
        self.child = None
        self.version = None

    def stop(self):
        if self.child is not None:
            self.child.terminate()
            try:
                self.child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.child.kill()
                self.child.wait(timeout=5)
            self.child = None
        power_on(self.output)

    def refresh(self):
        # Read bytes too: a save of the same value resets the countdown.
        try:
            stat = self.path.stat()
            version = (stat.st_mtime_ns, stat.st_ino)
        except FileNotFoundError:
            version = 'default'
        if version == self.version and (self.child is None or self.child.poll() is None):
            return
        self.stop()
        self.version = version
        seconds = read_seconds(self.path)
        if seconds:
            # swayidle executes event strings in a shell. Every token here is
            # fixed except the strictly validated compositor output name.
            self.child = subprocess.Popen([
                'swayidle', '-C', '/dev/null', '-w', '-S', 'seat0',
                'timeout', str(seconds),
                f'swaymsg output {self.output} power off', 'resume',
                f'swaymsg output {self.output} power on'])


def main():
    if os.getuid() == 0:
        raise SystemExit('Run in the kiosk user Sway session, not as root')
    if not os.environ.get('SWAYSOCK') or not os.environ.get('WAYLAND_DISPLAY'):
        raise SystemExit('Sway session environment required')
    runtime = Path(os.environ['XDG_RUNTIME_DIR'])
    with (runtime / 'spotify-kiosk-display-idle.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        supervisor = Supervisor(config_path(), discover_output())
        def shutdown(signum, frame):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, shutdown)
        signal.signal(signal.SIGINT, shutdown)
        try:
            while True:
                supervisor.refresh()
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            supervisor.stop()


if __name__ == '__main__':
    main()
