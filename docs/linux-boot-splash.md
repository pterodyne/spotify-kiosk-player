# Linux boot splash: Spotify Player

This is a **Plymouth Linux boot theme**, not an HTML/browser splash. The theme
lives in `plymouth/spotify-player/`; `scripts/install-boot-splash.sh` installs
exactly those four files into `/usr/share/plymouth/themes/spotify-player/`.
The transparent PNG contains the loader SVG's Spotify icon and the word
**Player** below it. Branding needs no initramfs fonts. A green bar pulses via
Plymouth's refresh callback and `Math.Sin`; it is not a completion estimate.
Plymouth messages, questions, and masked password prompts have callbacks.
Only normal system messages/prompts use Plymouth's text renderer/fonts;
password input is never logged by this theme.

## Preconditions and scope

Designed for the inspected Raspberry Pi Debian Plymouth 24.004.60 installation
with the `script.so` plugin, initramfs-tools, `/boot/firmware/cmdline.txt`, and
existing `auto_initramfs=1`. The HyperPixel overlay and every other firmware
setting are preserved. Firmware/logo phases before Linux cannot be replaced
by Plymouth. The display driver must become available early enough.

This is an explicit root operation, separate from application installation.
It does not install packages, stop the player, change browser launchers, or
reboot. Install missing dependencies through your normal system administration
process before proceeding: Plymouth with the script plugin, initramfs-tools,
and Python 3. `/usr/sbin` is explicitly on the script's PATH.

```sh
# Review first; no root or file changes needed:
bash scripts/install-boot-splash.sh --dry-run
# Explicitly opt in, with playback/reboot timing coordinated separately:
sudo bash scripts/install-boot-splash.sh --install
```

The installer appends only missing `quiet splash
plymouth.ignore-serial-consoles` tokens. It retains root/PARTUUID tokens,
serial/tty console tokens, and all other existing command-line contents.
Multi-line/empty cmdline files and missing auto_initramfs are refused.
A dry-run fixture may be selected with `--root DIRECTORY`; actual installation
and rollback cannot redirect the root.

Before its first boot/theme write it creates an owner-only timestamped backup
under `/var/backups/spotify-player-plymouth-*`, recording:

- Exact cmdline.txt and firmware config.txt, including overlays.
- Plymouth configuration, previous selected theme name, default-theme links,
  and an existing spotify-player theme directory if present.
- Existing `/boot/initrd.img-*` files and **both** firmware image paths,
  `/boot/firmware/initramfs8` and `/boot/firmware/initramfs_2712`.
- A manifest of previously absent paths, so rollback removes created files.

Free space is checked before backups/rebuild (including 128 MiB firmware
headroom). The selected theme is set with `plymouth-set-default-theme`, then
`update-initramfs -u -k all` is run. Any rebuild failure is fatal and prints a
rollback command; **do not reboot on failure**. A successful install also reads
back the theme and checks script/logo/bar membership with `lsinitramfs` in
each existing firmware-loaded image. This does not prove screen visibility.

## Rollback

Keep the exact `BACKUP:` directory printed by installation. Do not use a backup
from a different installation/device. Backups are local root-owned recovery
material; do not edit their manifest.

```sh
sudo bash scripts/install-boot-splash.sh --rollback /var/backups/spotify-player-plymouth-TIMESTAMP
```

Rollback restores the exact saved files, links, theme directory, and boot
images, and removes tracked paths that did not originally exist. It deliberately
**does not rebuild initramfs afterward**, which would overwrite the restored
images. It never reboots. If the device cannot boot, mount its filesystems on
another Linux machine and restore the files under `BACKUP/files/` to their
matching paths; consult `manifest.json` for paths that were originally absent.

## Verification and remaining physical check

```sh
python3 -m unittest discover -s tests -p test_plymouth_theme.py
bash -n scripts/install-boot-splash.sh
sudo /usr/sbin/plymouth-set-default-theme
sudo lsinitramfs /boot/firmware/initramfs8 | grep spotify-player
sudo lsinitramfs /boot/firmware/initramfs_2712 | grep spotify-player
```

Only inspect images that exist. Automated tests exercise asset dimensions,
callback presence, the installed native Plymouth script parser when available,
and installer dry-run without touching host boot files. Native parsing is not
a graphical renderer test. The target was inspected **read-only**; no theme,
initramfs, service, or boot setting was changed remotely during development.

Coordinate a real reboot before declaring this working: confirm the HyperPixel
shows the icon, **Player** underneath, a pulsing bar, then a clean handoff to the
application. Check recovery/prompts and keyboard access if encrypted storage is
used. Direct Chromium startup is a separate layer: it should wait for the local
application's health endpoint before opening, rather than adding an HTML logo
or opening a connection-error page. This theme does not implement that launcher
wait or extend Plymouth until application readiness.
