#!/usr/bin/env bash
# Keep the native boot screen visible until the local application is ready.
set -euo pipefail
for command in curl python3; do
    command -v "$command" >/dev/null || { echo "Missing $command" >&2; exit 1; }
done
browser=$(command -v chromium-browser || command -v chromium) || { echo 'Chromium not found' >&2; exit 1; }
attempts=${PLAYER_READY_ATTEMPTS:-60}
[[ "$attempts" =~ ^[1-9][0-9]*$ ]] && (( attempts <= 300 )) || { echo 'Invalid readiness attempt limit' >&2; exit 1; }
for ((i=1; i<=attempts; i++)); do
    if body=$(curl --fail --silent --show-error --connect-timeout 1 --max-time 2 http://127.0.0.1:5000/api/health) &&
        printf '%s' "$body" | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if isinstance(d,dict) and d.get("status")=="ok" else 1)' 2>/dev/null; then
        exec "$browser" --app=http://127.0.0.1:5000/ --noerrdialogs --disable-infobars "$@"
    fi
    if (( i < attempts )); then sleep 1; fi
done
echo 'Application did not become ready; browser not launched' >&2
exit 1
