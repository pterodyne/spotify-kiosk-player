# Hardware display idle timeout (Sway)

Settings → System replaces the old **Power Saving** CPU-clock toggle with one
**Display off after idle** slider: Never (0 seconds), 30 sec, 1 min, 5 min
(default), or 30 min. Changes save automatically on release/change, with a selected
value and save status. Never disables the timer and keeps/restores display power;
it does not turn power off.
The old setting changed `/boot/firmware/config.txt`; it never controlled display
power. Existing CPU clock configuration is deliberately left untouched.

`display_timeout.py` registers authenticated GET/POST
`/api/system/screen-timeout`. The slider GET uses `?unit=seconds` and receives
`{"seconds":300}`; POST sends exactly `{"seconds":30}` (allowed integer seconds:
0, 30, 60, 300, 1800). Legacy GET without the query returns `{"minutes":5}`;
for 30 seconds it returns `{"minutes":0.5}`, never a misleading disabled zero.
Legacy POST of exactly `{"minutes":N}` still accepts integers 0–120.
POST additionally requires the actual loopback peer, trusted Host/Origin, and JSON,
matching the keyboard bridge. Mixed minutes/seconds fields and unknown fields
are rejected; clients cannot send output names, commands, process IDs, or signals.
Canonical writes contain only integer seconds. Existing minutes-only files are
read without modification (`{"minutes":5}` means 300 seconds), migrating on the
next save. Legacy non-slider values remain effective and are visibly labeled in
the UI until explicitly changed. Canonical files accept the slider values and
whole-minute legacy values up to 7200 seconds. Invalid types, ranges, malformed
JSON, and mixed-format files fail safely to the 300-second default.
Preferences are atomically replaced with mode 0600 in
`$XDG_CONFIG_HOME/spotify-kiosk/display.json` (default `~/.config/...`, directory
0700). API and supervisor must run as the same kiosk user with the same HOME and
XDG_CONFIG_HOME.

## Existing-device integration (do not rerun the installer)

Install the distribution package:

```sh
sudo apt install swayidle
```

Add this once to the kiosk user's `~/.config/sway/config`, substituting the actual
checkout path (the new installer generates it automatically):

```sway
exec python3 /home/KIOSK_USER/spotify-kiosk-player/scripts/display-idle.py
```

To start without rebooting, from a terminal inside that user's running Sway
session, with its `SWAYSOCK`, `WAYLAND_DISPLAY`, and `XDG_RUNTIME_DIR`:

```sh
swaymsg exec 'python3 /home/KIOSK_USER/spotify-kiosk-player/scripts/display-idle.py'
```

Deploy the backend and frontend normally; restart the Flask service and refresh
the browser for new settings assets. Do not start this as root, from Flask, or as
a system service without the actual compositor session environment. A runtime
file lock prevents duplicate supervisors, including after accidental repeat exec.
No reboot, suspend, audio-service restart, browser overlay, or playback command is
used. Never / any save restores output power and updates the timer within about
one second. Touch activity is handled by swayidle's compositor resume event.

The supervisor discovers active outputs, prefers DPI-1, or accepts a single active
output. For multi-display ambiguity set `KIOSK_DISPLAY_OUTPUT=DPI-1` in the Sway
session; the name must be validated and active. No wildcard output targeting.
It starts `swayidle -C /dev/null -w -S seat0 timeout ... resume ...`; these flags
are documented in upstream swayidle 1.8.0. `-w` waits for event commands, **not** an
idle-inhibitor bypass. No unsupported `-I` option or blanket inhibitor-policy
changes are used. The observed browser had no active idle inhibitor. If this
changes during playback, inspect the live Sway tree before a narrowly scoped
policy change; tests here do not prove behavior with an application inhibitor.

Parent's hardware probe confirmed `swaymsg output DPI-1 power off` changes the
HyperPixel backlight sysfs `bl_power` from 0 to 4, and `power on` restores 0.
This is display power saving, **not disconnection of the entire board**: touch
electronics remain powered. Physical touch wake, idle timing during audible
playback, and startup after deployment still require target verification.
