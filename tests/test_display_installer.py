from pathlib import Path


def test_installer_starts_display_supervisor_in_sway_session():
    source = (Path(__file__).resolve().parents[1] / 'install.sh').read_text()
    assert 'sway swayidle wlr-randr' in source
    assert 'exec python3 ${INSTALL_DIR}/scripts/display-idle.py' in source
