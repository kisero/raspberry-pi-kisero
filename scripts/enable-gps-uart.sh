#!/usr/bin/env bash
# Enable the GPIO UART for a receive-only GPS on Raspberry Pi OS.
set -euo pipefail
if (( EUID != 0 )); then echo 'Run with sudo.' >&2; exit 1; fi
boot=/boot/firmware
mountpoint -q "$boot"
backup=$(mktemp -d /root/kisero-gps-boot.XXXXXX)
cp -- "$boot/config.txt" "$boot/cmdline.txt" "$backup/"
python3 - "$boot" <<'PY'
import re
import sys
from pathlib import Path

boot = Path(sys.argv[1])
config, cmdline = boot / 'config.txt', boot / 'cmdline.txt'
original = cmdline.read_text().strip()
if not original or '\n' in original or not any(x.startswith('root=') for x in original.split()):
    raise SystemExit('Unexpected boot command line; no changes made.')
tokens = [x for x in original.split() if not re.match(r'^console=(?:serial0|ttyS0|ttyAMA0)(?:,|$)', x)]
contents = config.read_text()
block = '\n[all]\n# Kisero GPS UART\nenable_uart=1\n'
if not contents.endswith(block):
    config.write_text(contents.rstrip('\n') + '\n' + block)
if tokens != original.split():
    cmdline.write_text(' '.join(tokens) + '\n')
PY
sync
printf 'GPS UART configured. Boot-file backups: %s\nReboot to apply.\n' "$backup"
