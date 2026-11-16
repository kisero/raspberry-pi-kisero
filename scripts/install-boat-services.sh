#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
test -s /etc/kisero/sensor.env
if [[ ! -d /var/lib/kisero ]]; then
    install -d -o admin -g admin -m 0700 /var/lib/kisero
fi
install -d -m 0755 /opt/kisero/collector
install -m 0644 collector/boat_tracker.py collector/yacht_fetch.py collector/pipeline.py /opt/kisero/collector/
install -m 0644 systemd/kisero-boat.service systemd/kisero-yacht.service systemd/kisero-yacht.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable kisero-boat.service kisero-yacht.timer
systemctl restart kisero-boat.service kisero-yacht.timer
