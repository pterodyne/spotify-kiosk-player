# Read-only SD root with persistent USB state

## Scope and findings (Pi inspection, 2026-11-09)

This is a staged installer, **not deployed or reboot-tested**. No partition resizing,
formatting, mounts, service stops, package installation or reboot is performed by
`setup-readonly-root.py`. The default invocation prints a plan without writing.

The Pi runs Debian 13; root is ext4 `/dev/mmcblk0p2`, firmware is vfat
`/dev/mmcblk0p1`. Root has approximately 106 GiB free; no SD resize is needed.
Swap is `/dev/zram0`, not an SD swap file. `auto_initramfs=1` selects firmware
images `/boot/firmware/initramfs8` and `initramfs_2712`; the matching initrd files
are `/boot/initrd.img-6.18.50+rpt-rpi-{v8,2712}`. Preserve **both architectures**,
Plymouth theme and the firmware image copy/update hooks, not just the running
kernel's `/boot/initrd.img-*`.

Inspected Debian package `overlayroot 0.18.debian14` using unprivileged
`apt download` / `dpkg-deb -x` in scratch. `/etc/overlayroot.conf` documents
`overlayroot=tmpfs:recurse=0`: only root is overlaid; other fstab filesystems
remain real writable mounts. Default recurse=1 would overlay the USB too.
`usr/share/initramfs-tools/scripts/init-bottom/overlayroot`, function
`overlayrootify_fstab`, only transforms `/` when recurse=0. Kernel command-line
`overlayroot=disabled` overrides configuration, even one embedded in initramfs.
The package installs an initramfs hook and init-bottom script: install and rebuild
before activation. Keep overlayroot config disabled/default; activate through the
single kernel command-line token so FAT-only recovery remains possible.

Approved USB has already been formatted **by the operator**, ext4 label
`kiosk-persist`, UUID `1f404a93-c5fe-45eb-9cd8-8e8cde1c1a37`.
The previous exFAT UUID `6AEE-24D4` is intentionally rejected. Never reformat
from these instructions. Mount `/srv/kiosk-data` root-owned 0700 with
`noatime,nodev,nosuid`, **not noexec** (the app and venv execute there).

## Persistence boundary and risks

Bind only these directories, preserving absolute directory layout on USB:

* `/home/pterodyne` — app, venv, settings, dynamically located Spotipy `.cache*`,
  Chromium cookies/preferences, librespot credential cache and user services.
  The full home avoids guessing working-directory-dependent cache locations.
  This also puts source, SSH keys, shell state and home backups on USB; protect
  physical access. USB failure now prevents kiosk startup and requires recovery.
* `/var/lib/bluetooth` — pairings and adapter state.
* `/var/lib/NetworkManager` — persistent network runtime state.
* `/etc/NetworkManager/system-connections` — root-owned connection profiles.

Root and boot SD writes are protected, not USB writes. ext4 journaling reduces
filesystem damage but cannot guarantee last-write integrity or credential safety
under power removal. Back up USB securely. `/etc` changes outside these binds,
package installs and system-level app config changes disappear in overlay mode.
User app updates persist because home is on USB.

The USB and binds are required mounts, no `nofail` or automount fallback.
`x-systemd.requires-mounts-for=/srv/kiosk-data` orders each bind after USB.
NetworkManager and Bluetooth have explicit RequiresMountsFor dependencies; user
manager UID1000 and display manager require home. Missing USB intentionally
leads to failed mounts/emergency recovery, not an apparently working empty home
or discarded Wi-Fi pairing updates. SSH may be unavailable in this case; have a
physical console/SD reader available before activation.

## Operator deployment phases (not automatic)

1. **Before installing overlayroot**, create a root-only backup outside home:
   `/root/kiosk-readonly-prepackage`, chmod 0700. Archive `/boot` (including
   firmware images/config/cmdline), `/etc/fstab`, `/etc/plymouth`,
   `/etc/alternatives/default.plymouth`, any existing overlayroot config, and
   `readlink -f /etc/alternatives/default.plymouth`. Record image hashes, selected
   theme and `dpkg-query -W` package versions. Check free space first. These
   backups contain sensitive config: never publish them.
2. Install overlayroot normally with apt. Package hooks may rebuild initramfs.
   Do not use raspi-config's overlay switch: this installer owns the token and
   explicit boot-ro fstab entry. Do not activate an overlay yet.
3. Copy this installer to `/usr/local/sbin/setup-readonly-root.py`, root-owned
   0755, **before** binding home. Run it from there, not the path being hidden.
4. Initial copy may run while services are live, but is not authoritative.
   For each path below use `rsync -aHAXx --numeric-ids` as root. Pre-create each
   destination parent; copy the directory itself (no trailing source slash)
   into its matching parent so directory ownership/mode are retained:

   ```sh
   sudo mkdir -p /srv/kiosk-data/home /srv/kiosk-data/var/lib /srv/kiosk-data/etc/NetworkManager
   sudo rsync -aHAXx --numeric-ids /home/pterodyne /srv/kiosk-data/home/
   sudo rsync -aHAXx --numeric-ids /var/lib/bluetooth /var/lib/NetworkManager /srv/kiosk-data/var/lib/
   sudo rsync -aHAXx --numeric-ids /etc/NetworkManager/system-connections /srv/kiosk-data/etc/NetworkManager/
   ```

5. **Final sync deliberately interrupts network/SSH and playback.** Keep a local
   recovery console available, but run the finalizer as an independent root
   system service, not a shell child of SSH. Initial copies of **all four** trees
   above must already exist. Close other home writers (editors, downloads,
   deployment jobs, other sessions); this is not a general filesystem freeze.
   Do not edit home during this operation, including from the supervising shell.
   Copy the reviewed finalizer outside home and run from `/root`:

   ```sh
   sudo install -o root -g root -m 0700 scripts/finalize-persistence-copy.py /root/finalize-persistence-copy.py
   sudo systemd-run --unit=kiosk-final-copy --description='Kiosk authoritative persistence copy' \
     --property=User=root --property=WorkingDirectory=/root --property=RemainAfterExit=yes \
     --property=StandardOutput=journal --property=StandardError=journal \
     --property=TimeoutStopSec=180 --property=KillMode=mixed \
     /usr/bin/python3 /root/finalize-persistence-copy.py
   ```

   Do **not** add `--scope`, `--pipe`, `--pty` or `--wait`; the system manager owns
   the process independently of SSH. Network loss is expected. The finalizer
   verifies the exact approved writable ext4 UUID, private root-owned 0700 USB
   top, real nonsymlink source/destination directory chains and user runtime,
   and discovers/validates the UID1000 Sway socket before stopping anything.
   It invalidates any old marker, stops active NetworkManager and Bluetooth,
   and uses the user bus (`sudo -u pterodyne env XDG_RUNTIME_DIR=/run/user/1000
   DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus systemctl --user`) to stop
   `spotify-player.service` and `librespot.service`. It never stops `user@1000`
   or the display manager/SSH. UID1000 Chromium receives TERM and must exit
   within 45 seconds; it is never forcibly killed.

   Only then does it repeat all four exact directory copies with
   `rsync -aHAXx --delete --numeric-ids`, followed by
   `rsync -aHAXxnci --delete --numeric-ids` for checksum/itemized comparison.
   Any rsync failure or **any comparison output** prevents attestation. On
   success the UUID marker is atomically replaced, fsynced, root-owned 0600.
   A `finally` cleanup attempts every stopped service restart even on failure
   or TERM/INT, network first and librespot before player; Chromium is restored
   through validated Sway IPC and the shared `launch-player.sh` app-mode
   launcher, only if it was running before. No bind mounts, overlay changes,
   initramfs updates or reboot occur. SIGKILL/power loss cannot run cleanup;
   use the console if networking fails to return. A refused Sway launch or
   service restart fails the job and removes the marker; Sway accepting exec
   is not proof the application/browser is healthy.

   Reconnect (or use console) and inspect **both** the unit result and journal:

   ```sh
   sudo systemctl show kiosk-final-copy.service -p ActiveState -p SubState -p Result -p ExecMainStatus
   sudo journalctl -u kiosk-final-copy.service -b --no-pager
   sudo systemctl is-active NetworkManager.service bluetooth.service
   sudo -u pterodyne env XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus \
     systemctl --user is-active librespot.service spotify-player.service
   ```

   Require `Result=success`, `ExecMainStatus=0` and the final success log; inspect
   browser/app health separately. Never fabricate the marker to bypass failure.
   Before retrying a failed/inactive run, inspect recovery, then
   `sudo systemctl reset-failed kiosk-final-copy.service` if necessary (a still
   loaded inactive unit may require `sudo systemctl stop kiosk-final-copy.service`
   and waiting for garbage collection, or use a fresh unit name and its journal).
6. Inspect and separately authorize config staging:

   ```sh
   sudo /usr/local/sbin/setup-readonly-root.py         # inspect plan
   sudo /usr/local/sbin/setup-readonly-root.py --apply # stages files only
   ```

   Apply checks real root, approved mounted writable ext4 UUID, root-owned
   nonsymlink USB top mode 0700 and regular nonsymlink root-owned marker mode
   0600 with matching UUID, destination/source owner/mode equality, profile
   permissions, installed package and absence of a running overlay. The marker
   attests a quiesced snapshot, not ongoing equality after services resume;
   rerun the finalizer immediately before later coordinated bind activation if
   new live state must be captured. It backs up all files it replaces, records
   which drop-ins were previously absent, and copies `/boot` plus Plymouth config
   to `/root/kiosk-readonly-backups/TIMESTAMP` before writes. This backup is in
   addition to the mandatory **pre-package** backup. A disk error can leave a
   partially staged config: restore from backup rather than blindly retrying.
7. Run `findmnt --verify --verbose`, `systemctl daemon-reload`, inspect generated
   mount units/dependency graph for cycles, and `update-initramfs -u -k all`.
   Confirm both firmware initramfs images were updated by the installed hooks;
   use `lsinitramfs` to verify overlayroot hook/script and Plymouth theme assets
   in **each firmware-loaded image**. Compare images/hashes against their
   corresponding `/boot/initrd.img-*`; investigate stale copies, don't assume
   a successful rebuild updates firmware. Confirm `auto_initramfs=1` still exists
   and all display overlays, splash flags and selected Plymouth theme survived.
8. Do not run blanket `mount -a` while the session is using home. With writers
   stopped, manually mount each bind if validating before reboot. Validate real
   mounts using `findmnt --mountpoint PATH`; reading a directory is not proof.
   Restore services only after all four binds succeed. Reboot only after the
   operator separately authorizes it. There is deliberately no reboot command
   in this installer or runbook.

## Keep high-volume caches in RAM

The inspected installed `librespot --help` supports `--disable-audio-cache` and
`--system-cache PATH`. Add `--disable-audio-cache` to its existing ExecStart,
preserving the existing cache/system-cache path and credentials. Never use
`--disable-credential-cache`. Confirm actual process arguments after restart.
For Chromium add `--disk-cache-dir=/tmp/kiosk-chromium-cache` to the actual shared
launcher (or a user-owned `/run/user/1000/...` directory). Keep the browser user
profile on persistent home: moving the whole profile to tmpfs loses login.
These flags are an operator follow-up, not silently rewritten by this installer.
`/tmp` must actually be tmpfs (verify `findmnt -T /tmp`); otherwise configure a
RAM mount or use `/run/user/1000`. Bound cache/RAM consumption and observe memory.

## Verification after coordinated boot

* `findmnt /` should show overlay; find `/media/root-ro` and verify underlying
  SD root is ro. `findmnt /boot/firmware` must show ro.
* Exact mountpoints `/srv/kiosk-data` and all four bind paths must resolve to
  the approved USB ext4 filesystem with rw; verify service mount dependencies.
* Write disposable probe files on a nonpersistent root path and persistent
  home, then coordinate a second boot: only persistent probe should survive.
  Delete probes afterward. Never use real credential files as probes.
* Verify app localhost health, Spotify OAuth refresh, Chromium saved session,
  Bluetooth pairings and Wi-Fi reconnect. Verify Plymouth visually and actual
  audio playback separately. Unit tests cannot establish any of these.
* Test missing-USB fail-closed recovery only with local console access and a
  separate authorized boot window; never unplug mounted USB while running.

## Maintenance and rollback

To temporarily disable overlay, edit the **SD FAT cmdline.txt** externally,
replace the only `overlayroot=tmpfs:recurse=0` token with
`overlayroot=disabled`, and keep the command line one line. This works even if
SSH cannot start. Boot-ro remains until explicitly remounted in maintenance.
USB is still required by fstab, even with overlay disabled.

For normal maintenance keep USB connected, boot disabled, verify `/` is plain
ext4 rw, temporarily remount boot rw if needed, update packages/config, rebuild
and verify both firmware initramfs images/Plymouth as above, then restore the
single overlay token and boot ro. Don't remount the live overlay lower root rw
as a shortcut. Coordinate each reboot separately.

For complete rollback, in disabled maintenance mode restore backed-up
`/etc/fstab`, firmware cmdline and every changed service drop-in. Consult
`manifest.json`: remove drop-ins marked previously absent rather than leaving
new dependencies behind. Restore full firmware images/config/Plymouth only if
needed, using the pre-package backup when undoing package-triggered image
changes. Reload systemd. Do not unmount home under active writers. Once the
binds are no longer active, choose whether to restore newer USB home/state onto
SD using an offline/local-console rsync; original SD copies are deliberately
not deleted but become stale after USB use. For a missing-USB emergency, an
external SD reader can replace cmdline and restore original fstab/drop-ins from
the root partition before boot. Simply disabling overlay does not remove the
USB requirement. Keep USB attached until the rollback is fully verified.

## Offline tests

`python3 -m unittest discover -s tests -p test_readonly_setup.py -v`

`--root PATH` supports generated-config fixture dry-runs; applying to a fixture
is intentionally forbidden. Tests exercise generated fail-closed mounts,
boot-ro/token preservation, rejected old UUID, no-write dry-run and fixture
apply rejection. Metadata tests use real temporary directories, modes and
symlinks; only uid ownership is mocked when running without root. Finalizer
fixtures assert stop/sync/checksum/marker ordering, failure restoration, exact
UUID rejection, empty checksum output and atomic private marker creation.
They do not simulate initramfs, real systemd/Sway lifecycle or power loss.
