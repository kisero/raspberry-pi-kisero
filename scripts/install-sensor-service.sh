#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "$EUID" -ne 0 ]]; then
  echo "Run this installer with sudo from the checked-out repository." >&2
  exit 1
fi
if [[ ! -f /etc/kisero/sensor.env ]]; then
  echo "Create /etc/kisero/sensor.env with KISERO_API_URL and KISERO_DEVICE_TOKEN first." >&2
  exit 1
fi
if ! grep -q '^KISERO_API_URL=https://' /etc/kisero/sensor.env || ! grep -q '^KISERO_DEVICE_TOKEN=.' /etc/kisero/sensor.env; then
  echo "The sensor environment file is missing required settings." >&2
  exit 1
fi

install -d -o root -g root -m 0755 /opt/kisero/collector /etc/kisero
install -d -o root -g root -m 0755 /etc/systemd/system
install_file() {
  local source="$1" destination="$2" mode="$3"
  if [[ "$source" -ef "$destination" ]]; then
    chmod "$mode" "$destination"
  else
    install -m "$mode" "$source" "$destination"
  fi
}
install_file "$repo_dir/collector/sensor_collector.py" /opt/kisero/collector/sensor_collector.py 0644
install_file "$repo_dir/systemd/kisero-sensor.service" /etc/systemd/system/kisero-sensor.service 0644
install_file "$repo_dir/systemd/kisero-sensor.timer" /etc/systemd/system/kisero-sensor.timer 0644
chown root:root /etc/kisero/sensor.env
chmod 0600 /etc/kisero/sensor.env
systemctl daemon-reload
systemctl enable --now kisero-sensor.timer
echo "Installed and enabled the five-minute sensor timer."
