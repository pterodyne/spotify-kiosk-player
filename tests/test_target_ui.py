from pathlib import Path


def test_target_ui_distinguishes_selection_and_deselects():
    source = (Path(__file__).parents[1] / 'static/js/app.js').read_text()
    assert "if (device.is_selected) div.classList.add('active')" in source
    assert 'selectDevice(device.is_selected ? null : device.id)' in source
    assert 'apiData.target_error' in source
    assert 'Only allowed Spotify targets are listed' in source
    assert "showToast(data.error || t('error.selectDevice'), 'error')" in source
