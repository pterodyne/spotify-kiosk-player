"""Exercise real routes without importing hardware/startup code."""
import ast
import importlib.util
import os
from pathlib import Path
from functools import wraps
from types import SimpleNamespace
import pytest

spec = importlib.util.spec_from_file_location('target_module', Path(__file__).parents[1] / 'playback_target.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def scope_for(tmp_path, monkeypatch, devices, payload=None):
    monkeypatch.setenv('SPOTIFY_DEVICE_NAME', 'novaplayer,Phone')
    calls = []
    sp = SimpleNamespace(devices=lambda: {'devices': devices}, **{
        name: (lambda *args, _name=name, **kw: calls.append((_name, args, kw)))
        for name in ('start_playback', 'pause_playback', 'next_track', 'previous_track', 'shuffle', 'volume', 'seek_track', 'transfer_playback')})
    target = module.PlaybackTarget(tmp_path / 'target.json', 'novaplayer')
    scope = dict(os=os, wraps=wraps, playback_target=target, TargetError=module.TargetError,
                 get_spotify_client=lambda: sp, jsonify=lambda x: x, t=lambda x: x,
                 request=SimpleNamespace(get_json=lambda **kw: payload or {}),
                 spotipy=SimpleNamespace(exceptions=SimpleNamespace(SpotifyException=RuntimeError)))
    names = {'activate_local_device', 'find_device_by_name', 'transfer_playback_local', 'device_name_allowed', 'spotify_playback_action', 'play', 'play_track', 'pause', 'next_track', 'previous_track', 'toggle_shuffle', 'set_volume', 'seek_track', 'transfer_playback', 'get_devices'}
    nodes = []
    for node in ast.parse((Path(__file__).parents[1] / 'app.py').read_text()).body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            node.decorator_list = [d for d in node.decorator_list if isinstance(d, ast.Name)]
            nodes.append(node)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'app.py', 'exec'), scope)
    return scope, calls, target


DEVICES = [{'id': 'local', 'name': 'novaplayer', 'is_active': False}, {'id': 'remote', 'name': 'Phone', 'is_active': True}]

@pytest.mark.parametrize('route,payload', [('play', {}), ('play_track', {'uri': 'spotify:track:x'}), ('play_track', {'uri': 'spotify:track:x', 'album_id': 'a'}), ('play_track', {'uri': 'spotify:track:x', 'playlist_id': 'p'}), ('play_track', {'uri': 'spotify:track:x', 'track_uris': ['spotify:track:x']}), ('pause', {}), ('next_track', {}), ('previous_track', {}), ('toggle_shuffle', {'state': True}), ('set_volume', {'volume_percent': 30}), ('seek_track', {'position_ms': 5})])
def test_controls_address_inactive_local(tmp_path, monkeypatch, route, payload):
    scope, calls, _ = scope_for(tmp_path, monkeypatch, DEVICES, payload)
    assert scope[route]() == {'success': True, **({'shuffle': True} if route == 'toggle_shuffle' else {'volume_percent': 30} if route == 'set_volume' else {'position_ms': 5} if route == 'seek_track' else {})}
    assert calls[0][2]['device_id'] == 'local'


def test_selection_persists_without_starting_audio(tmp_path, monkeypatch):
    scope, calls, target = scope_for(tmp_path, monkeypatch, DEVICES, {'device_id': 'remote'})
    assert scope['transfer_playback']()['success']
    assert calls == []
    assert module.PlaybackTarget(target.path, 'novaplayer').resolve(DEVICES)['id'] == 'remote'
    scope['play']()
    assert calls[0][2]['device_id'] == 'remote'


@pytest.mark.parametrize('selected', ['local', None])
def test_missing_or_disabled_never_falls_back(tmp_path, monkeypatch, selected):
    scope, calls, target = scope_for(tmp_path, monkeypatch, DEVICES[1:])
    target.select(selected)
    assert scope['play']()[1] == 409
    assert not calls


def test_deselect_and_filter(tmp_path, monkeypatch):
    scope, calls, target = scope_for(tmp_path, monkeypatch, DEVICES, {'device_id': None})
    assert scope['transfer_playback']()['success']
    with pytest.raises(module.TargetError, match='No playback target selected'):
        target.resolve(DEVICES)
    monkeypatch.setenv('SPOTIFY_DEVICE_NAME', 'novaplayer')
    scope, calls, target = scope_for(tmp_path, monkeypatch, DEVICES, {'device_id': 'remote'})
    monkeypatch.setenv('SPOTIFY_DEVICE_NAME', 'novaplayer')
    assert scope['transfer_playback']()[1] == 403
    assert len(scope['get_devices']()['devices']) == 1
    assert not calls


@pytest.mark.parametrize('payload,status', [({}, 400), ({'device_id': 'missing'}, 409), ({'device_id': ''}, 409)])
def test_invalid_selection_does_not_replace_previous_choice(tmp_path, monkeypatch, payload, status):
    scope, calls, target = scope_for(tmp_path, monkeypatch, DEVICES, payload)
    target.select('local')
    assert scope['transfer_playback']()[1] == status
    assert target.resolve(DEVICES)['id'] == 'local'
    assert not calls


def test_selected_target_filter_and_restriction_are_enforced(tmp_path, monkeypatch):
    scope, calls, target = scope_for(tmp_path, monkeypatch, DEVICES)
    target.select('remote')
    monkeypatch.setenv('SPOTIFY_DEVICE_NAME', 'novaplayer')
    assert scope['play']()[1] == 403
    monkeypatch.setenv('SPOTIFY_DEVICE_NAME', '')
    scope, calls, target = scope_for(tmp_path, monkeypatch, [{**DEVICES[0], 'is_restricted': True}])
    target.select('local')
    assert scope['play']()[1] == 409
    assert not calls


def test_device_listing_marks_intended_not_active(tmp_path, monkeypatch):
    scope, calls, _ = scope_for(tmp_path, monkeypatch, DEVICES)
    response = scope['get_devices']()
    assert response['selected_device_id'] == 'local'
    assert [d['id'] for d in response['devices'] if d['is_selected']] == ['local']
    assert not calls


@pytest.mark.parametrize('active', [True, False])
def test_registered_activation_selects_without_audio(tmp_path, monkeypatch, active):
    scope, calls, target = scope_for(tmp_path, monkeypatch, [{**DEVICES[0], 'is_active': active}],
                                   {'device_name': 'novaplayer', 'ip': '192.0.2.1', 'port': 1234})
    assert scope['activate_local_device']()['success']
    assert target.resolve(DEVICES)['id'] == 'local'
    assert not calls


def test_local_selection_requires_registered_target(tmp_path, monkeypatch):
    scope, calls, target = scope_for(tmp_path, monkeypatch, DEVICES, {'device_id': 'local'})
    assert scope['transfer_playback_local']()['success']
    assert target.resolve(DEVICES)['id'] == 'local'
    assert not calls
