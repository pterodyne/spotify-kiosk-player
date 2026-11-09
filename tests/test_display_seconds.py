import json
import pytest
import display_timeout as d


def test_seconds_persistence_and_legacy(tmp_path):
    path = tmp_path / 'display.json'
    assert d.read_seconds(path) == 300
    path.write_text('{"minutes":5}')
    assert d.read_seconds(path) == 300
    d.save_seconds(path, 30)
    assert json.loads(path.read_text()) == {'seconds': 30}
    assert d.read_seconds(path) == 30
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('data', [{'seconds': 31}, {'seconds': True}, {'seconds': 30, 'minutes': 5}, {'minutes': False}, [], {'seconds': -1}, {'seconds': 30.0}])
def test_invalid_persistence_falls_back(tmp_path, data):
    path = tmp_path / 'display.json'
    path.write_text(json.dumps(data))
    assert d.read_seconds(path) == 300


def test_seconds_api(tmp_path):
    from flask import Flask
    app = Flask(__name__)
    app.secret_key = 'test'
    app.config['DISPLAY_TIMEOUT_PATH'] = tmp_path / 'display.json'
    d.register_display_routes(app)
    client = app.test_client()
    with client.session_transaction() as session:
        session['token_info'] = {'access_token': 'test'}
    for seconds in (0, 30, 60, 300, 1800):
        response = client.post('/api/system/screen-timeout', base_url='http://localhost:5000', headers={'Origin': 'http://localhost:5000'}, json={'seconds': seconds})
        assert response.status_code == 200
        assert response.json['seconds'] == seconds
        assert client.get('/api/system/screen-timeout?unit=seconds').json == {'seconds': seconds}
    for body in ({'seconds': True}, {'seconds': 31}, {'seconds': 30, 'minutes': 0}, {'seconds': '30'}):
        assert client.post('/api/system/screen-timeout', base_url='http://localhost:5000', headers={'Origin': 'http://localhost:5000'}, json=body).status_code == 400
