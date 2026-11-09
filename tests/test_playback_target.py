import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('playback_target', Path(__file__).parents[1] / 'playback_target.py')


def test_default_inactive_local(tmp_path):
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    target = module.PlaybackTarget(tmp_path / 'target.json', 'novaplayer')
    devices = [{'id': 'remote', 'name': 'Phone', 'is_active': True},
               {'id': 'local', 'name': 'novaplayer', 'is_active': False}]
    assert target.resolve(devices)['id'] == 'local'


@pytest.mark.parametrize('selection', ['remote', None])
def test_deliberate_selection_survives_restart(tmp_path, selection):
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    path = tmp_path / 'config' / 'target.json'
    target = module.PlaybackTarget(path, 'novaplayer')
    target.select(selection)
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    restarted = module.PlaybackTarget(path, 'novaplayer')
    devices = [{'id': 'local', 'name': 'novaplayer'}, {'id': 'remote', 'name': 'Phone'}]
    if selection:
        assert restarted.resolve(devices)['id'] == 'remote'
        with pytest.raises(module.TargetError, match='unavailable'):
            restarted.resolve(devices[:1])
    else:
        with pytest.raises(module.TargetError, match='No playback target selected'):
            restarted.resolve(devices)


def test_missing_default_never_uses_active_remote(tmp_path):
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    target = module.PlaybackTarget(tmp_path / 'target.json', 'novaplayer')
    with pytest.raises(module.TargetError, match='unavailable'):
        target.resolve([{'id': 'remote', 'name': 'Phone', 'is_active': True}])


@pytest.mark.parametrize('contents', ['null', '{}', '{broken', '[]'])
def test_invalid_config_fails_closed(tmp_path, contents):
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    path = tmp_path / 'target.json'
    path.write_text(contents)
    with pytest.raises(module.TargetError, match='configuration'):
        module.PlaybackTarget(path, 'novaplayer').resolve([{'id': 'local', 'name': 'novaplayer'}])
