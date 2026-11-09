import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def run_launcher(tmp_path, responses):
    state = tmp_path / 'count'
    log = tmp_path / 'browser'
    for name, body in {
        'curl': 'n=$(cat "$COUNT" 2>/dev/null || echo 0); n=$((n+1)); echo "$n" > "$COUNT"\ncase "$n" in\n' + ''.join(f'{i}) {response};;\n' for i, response in enumerate(responses, 1)) + '*) exit 7;; esac\n',
        'chromium-browser': 'cat "$COUNT" > "$LOG"; printf "%s\\n" "$@" >> "$LOG"\n',
        'chromium': 'cat "$COUNT" > "$LOG"; printf "%s\\n" "$@" >> "$LOG"\n',
        'sleep': 'exit 0\n',
    }.items():
        path = tmp_path / name
        path.write_text('#!/bin/bash\n' + body)
        path.chmod(0o755)
    env = dict(os.environ, PATH=str(tmp_path) + ':' + os.environ['PATH'], COUNT=str(state), LOG=str(log), PLAYER_READY_ATTEMPTS='4')
    result = subprocess.run(['bash', str(ROOT / 'scripts/launch-player.sh')], env=env, capture_output=True, text=True)
    return result, log, state


def test_waits_through_transport_bad_json_and_not_ready(tmp_path):
    result, log, _ = run_launcher(tmp_path, ['exit 7', "echo invalid", "echo '{\"status\":\"starting\"}'", "echo '{\"status\":\"ok\"}'"])
    assert result.returncode == 0, result.stderr
    assert log.read_text().splitlines()[0] == '4'
    assert '--app=http://127.0.0.1:5000/' in log.read_text()
    assert 'file://' not in log.read_text()


def test_exhaustion_never_launches(tmp_path):
    result, log, state = run_launcher(tmp_path, ["echo '{\"status\":\"not ok\"}'"] * 4)
    assert result.returncode != 0
    assert state.read_text().strip() == '4'
    assert not log.exists()
