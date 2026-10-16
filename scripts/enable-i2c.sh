#!/usr/bin/env bash
set -euo pipefail

config="${1:-/boot/firmware/config.txt}"
if [[ ! -f "$config" ]]; then
  echo "Raspberry Pi boot configuration not found: $config" >&2
  exit 1
fi

sudo python3 - "$config" <<'PY'
from pathlib import Path
import os
import shutil
import stat
import sys
import tempfile

path = Path(sys.argv[1])
text = path.read_text()
lines = text.splitlines(keepends=True)
active = [i for i, line in enumerate(lines) if line.strip() == "dtparam=i2c_arm=on"]
if active:
    print(f"I2C is already enabled in {path}")
    raise SystemExit(0)

commented = [i for i, line in enumerate(lines) if line.strip() == "#dtparam=i2c_arm=on"]
if commented:
    i = commented[0]
    lines[i] = lines[i].replace("#dtparam=i2c_arm=on", "dtparam=i2c_arm=on", 1)
    lines = [line for n, line in enumerate(lines) if n not in commented[1:]]
else:
    lines.append("\n" if lines and not lines[-1].endswith("\n") else "")
    lines.append("dtparam=i2c_arm=on\n")

backup = path.with_name(path.name + ".pre-i2c")
if not backup.exists():
    shutil.copy2(path, backup)

metadata = path.stat()
fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
try:
    with os.fdopen(fd, "w") as output:
        output.writelines(lines)
    os.chmod(temporary, stat.S_IMODE(metadata.st_mode))
    os.chown(temporary, metadata.st_uid, metadata.st_gid)
    os.replace(temporary, path)
except Exception:
    try:
        os.unlink(temporary)
    except FileNotFoundError:
        pass
    raise

print(f"Enabled I2C in {path}; backup saved as {backup}")
PY
