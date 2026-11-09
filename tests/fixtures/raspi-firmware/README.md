# Reviewed Raspberry Pi initramfs hook

`z50-raspi-firmware` is an exact, unmodified read-only SSH capture of
`/etc/initramfs/post-update.d/z50-raspi-firmware` from
`pterodyne@192.168.100.87`. Target SHA256:
`827fb7253c8cdcba0d3530fb8ed0d116ccc214cf9c97201c60dca46901c60ec3`.

The reviewed hook sets firmware_dst=/boot/firmware, sources
/etc/default/raspi-firmware, and under INITRAMFS=auto constructs destinations
from the kernel flavour. v8 maps to initramfs8; 2712 maps to initramfs_2712.
The installer intentionally rejects the other hook-supported flavours
(v6, v7, v8-rt): its firmware validation covers only v8 and 2712.
The captured target has 6.18.50+rpt-rpi-v8 and 6.18.50+rpt-rpi-2712;
its raspi-firmware defaults contain comments only.

Do not regenerate this fixture or update the allowlisted digest without
reviewing the entire new hook, sourced configuration, and output mapping.
Tests never execute the fixture or source the defaults.
