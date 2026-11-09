# Optional on-screen keyboard (Sway / Wayland)

This is an opt-in helper for the **Lite Sway kiosk** configured by `install.sh`.
It does not change the installer, Chromium flags, desktop autostart, LightDM,
or services. Run it as the kiosk's normal user, **not with sudo**. Python 3,
Sway, and `pkill` (Debian package `procps`) are prerequisites.

```sh
bash scripts/setup-keyboard.sh --help
bash scripts/setup-keyboard.sh --dry-run
# If wvkbd is already installed:
bash scripts/setup-keyboard.sh
# Otherwise: explicitly authorize the package installation and configuration:
bash scripts/setup-keyboard.sh --install --yes
```

`--install` checks `apt-cache policy wvkbd` for an available candidate before
calling `sudo apt-get install -y -- wvkbd`. Repository/package availability
varies by Raspberry Pi OS/Debian release; no repository changes, downloads from
unverified sources, or automatic apt update are attempted. If no candidate is
available, review your distribution repositories (and optionally run
`sudo apt update` yourself), then retry. `--install` without `--yes` refuses
installation. `--install --dry-run` checks availability but never invokes sudo.
Plain `--dry-run` needs no installed wvkbd and prints the proposed configuration
without writing anything or starting processes.

The default config is `${XDG_CONFIG_HOME:-$HOME/.config}/sway/config`.
Use `--config /path/to/config` for another existing config. Missing configs and
symlinks are refused. Review custom includes/bindings yourself for conflicts.
The helper preserves existing Chromium/output settings, makes a unique
`config.keyboard-backup.*` alongside the config before each actual change,
and atomically writes one marked block. Repeating it is idempotent; malformed
markers are refused. Do not edit concurrently with another configuration tool.
Rerunning the main installer may overwrite Sway config; rerun this helper after
that if desired.

The generated block is:

```sway
# BEGIN spotify-kiosk optional wvkbd
exec wvkbd-mobintl --hidden
bindsym Mod4+Ctrl+k exec pkill -RTMIN -u "$(id -u)" -x wvkbd-mobintl
# END spotify-kiosk optional wvkbd
```

Restart the Sway session when convenient to start the keyboard hidden. `exec`
is deliberately not `exec_always`: reload does not spawn duplicate keyboards.
No session restart or reload is performed automatically. To test immediately,
run `wvkbd-mobintl --hidden` once in a terminal inside the kiosk's Sway session
(if not already running), then press **Super+Ctrl+k**. The binding toggles all
exact-name `wvkbd-mobintl` processes owned by this user, not other users; avoid
running multiple instances/sessions under the same account.

## Touchscreen-only limitation and auto-show compatibility

**The manual shortcut requires a physical keyboard.** A hidden keyboard cannot
be opened by tapping an ordinary Chromium input field in this configuration.
There is no touch button, gesture, HTTP control endpoint, or privileged/root
service added here. For initial login, keep a USB/Bluetooth keyboard available,
or have an administrator show the running keyboard from a same-user terminal:

```sh
pkill -USR2 -u "$(id -u)" -x wvkbd-mobintl  # show
pkill -USR1 -u "$(id -u)" -x wvkbd-mobintl  # hide
pkill -RTMIN -u "$(id -u)" -x wvkbd-mobintl # toggle
```

An authenticated SSH session as that user can send these signals too; it cannot
launch a Wayland client without the correct session environment. Once shown,
wvkbd injects virtual keyboard events into the focused application. Test actual
touch input, focus, overlay visibility above fullscreen Chromium, layout,
rotation, password fields and Spotify login on the target display before
relying on it. **Touchscreen-only login has not been proven by these tests.**

Current upstream wvkbd documents `--auto` for automatic show/hide using the
compositor's `zwp_input_method_v2` protocol. This is intentionally **not enabled**:
older distro builds may not have the option; Sway must support the input-method
protocol and the Chromium build must activate a compatible Wayland text-input
protocol. The installer's `--ozone-platform=wayland` selects native Wayland but
alone does not guarantee text-input/IME integration or automatic pop-up.
Chromium IME flags and text-input protocol selection vary by version; check
local Chromium and compositor documentation rather than assuming a universal
flag combination. XWayland and other desktop compositors are outside this
helper's scope. Even if you experiment with `--auto`, verify both show and hide
on your actual login page and retain a manual recovery method.

Upstream references (flags/signals checked against README and source):
- https://github.com/jjsullivan5196/wvkbd/blob/master/README.md
- https://github.com/jjsullivan5196/wvkbd/blob/master/main.c

Upstream source documents `--hidden`, SIGUSR1=hide, SIGUSR2=show,
SIGRTMIN=toggle. Verify your installed version's `wvkbd-mobintl --help` before
use; distro versions may lag upstream.

## Undo and tests

Remove the entire BEGIN/END marked block (not unrelated config), or restore the
specific backup you want after checking for later changes. Stop your own
keyboard with `pkill -TERM -u "$(id -u)" -x wvkbd-mobintl`, then restart the
Sway session. Removing the package is optional and left to the administrator.

```sh
python3 -m unittest discover -s tests -p test_keyboard_setup.py -v
```

Tests use a temporary HOME/config and command stubs; they do not install
packages, run sudo, start a compositor/keyboard, or change the real user config.
They establish config generation/backup/idempotency and refusal/dry-run behavior,
not hardware or browser login compatibility.
