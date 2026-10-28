#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
install -d -o admin -g admin -m 0700 /var/lib/kisero
install -d -m 0755 /opt/kisero/collector
install -m 0644 collector/alarm.py /opt/kisero/collector/alarm.py
install -m 0644 systemd/kisero-alarm.service /etc/systemd/system/kisero-alarm.service
test -s /etc/kisero/sensor.env
systemctl daemon-reload
systemctl enable --now kisero-alarm.service
