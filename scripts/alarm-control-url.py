#!/usr/bin/env python3
"""Run privately on Pi with sudo; never put the resulting capability in Git."""
import hashlib
import hmac
from pathlib import Path
settings = dict(line.split('=', 1) for line in Path('/etc/kisero/sensor.env').read_text().splitlines()
                if line and not line.startswith('#') and '=' in line)
token = settings['KISERO_DEVICE_TOKEN'].strip().strip('\"\'')
capability = hmac.new(token.encode(), b'kisero-alarm-control-v1', hashlib.sha256).hexdigest()
print('https://kisero.org/alarm.html#' + capability)
