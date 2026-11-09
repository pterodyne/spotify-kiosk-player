"""Persistent intended Spotify target; never substitute the account's active device."""
import json
import os
from pathlib import Path
import tempfile


class TargetError(ValueError):
    pass


class PlaybackTarget:
    def __init__(self, path, default_name):
        self.path = Path(path)
        self.default_name = default_name

    def select(self, device_id):
        if device_id is not None and (not isinstance(device_id, str) or not device_id.strip()):
            raise TargetError('Select a valid device ID or null to disable playback.')
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.path.parent, 0o700)
        fd, temporary = tempfile.mkstemp(dir=self.path.parent, prefix='.target-')
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump({'device_id': device_id, 'disabled': device_id is None}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def resolve(self, devices):
        try:
            state = json.loads(self.path.read_text())
            if state is None:
                raise TargetError('Invalid playback target configuration; select a target again in Devices.')
        except FileNotFoundError:
            state = None
        except (OSError, ValueError) as exc:
            raise TargetError('Cannot read playback target configuration; select a target again in Devices.') from exc
        if state is not None:
            if not isinstance(state, dict) or not isinstance(state.get('disabled'), bool):
                raise TargetError('Invalid playback target configuration; select a target again in Devices.')
            if state['disabled']:
                raise TargetError('No playback target selected. Select a target in Devices to enable playback.')
            selected = state.get('device_id')
            for device in devices:
                if selected and device.get('id') == selected:
                    return device
            raise TargetError(f"Playback target '{selected}' unavailable. Open Spotify on the same account or explicitly select another target in Devices.")
        matches = [d for d in devices if d.get('name', '').casefold() == self.default_name.casefold() and d.get('id')]
        if len(matches) == 1:
            return matches[0]
        raise TargetError(f"Playback target '{self.default_name}' unavailable. Open Spotify on the same account and register this player, or select another allowed target in Devices.")
