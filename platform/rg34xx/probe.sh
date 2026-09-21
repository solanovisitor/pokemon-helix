#!/bin/sh
# Read-only portability inventory. No SSIDs, MACs, credentials, or save contents.
set -eu
printf 'os='; uname -s
printf 'architecture='; uname -m
printf 'kernel='; uname -r
printf 'word_size='; getconf LONG_BIT 2>/dev/null || true
for helix_binary in python3 uv mgba mgba-qt retroarch lsusb aplay arecord bluetoothctl; do
    if command -v "$helix_binary" >/dev/null 2>&1; then
        printf '%s=available\n' "$helix_binary"
    else
        printf '%s=missing\n' "$helix_binary"
    fi
done
if command -v python3 >/dev/null 2>&1; then python3 --version; fi
printf 'hardware_bridge_status=unverified; binary presence is not Lua/mailbox proof\n'
