#!/usr/bin/env bash
set -euo pipefail

connection_name="kisero-boat-ap"
ssid="${1:-Kisero-Boat}"

if [[ "$(id -u)" -eq 0 ]]; then
  echo "Run this as the admin user, not with sudo; the script uses sudo only for NetworkManager changes." >&2
  exit 2
fi

if [[ -z "${SSH_CONNECTION:-}" ]]; then
  echo "Run this over SSH through the Pi's wired Ethernet connection so Wi-Fi can be changed safely." >&2
  exit 2
fi

read -r ssh_client_ip _ <<<"$SSH_CONNECTION"
ssh_route="$(ip route get "$ssh_client_ip" 2>/dev/null || true)"
if [[ "$ssh_route" != *"dev eth0"* ]]; then
  echo "Your SSH route to $ssh_client_ip is not through eth0; refusing to change wlan0." >&2
  echo "Observed route: $ssh_route" >&2
  exit 2
fi

if [[ "$(nmcli -g WIFI-PROPERTIES.AP device show wlan0 2>/dev/null || true)" != "yes" ]]; then
  echo "NetworkManager does not report AP support for wlan0." >&2
  exit 2
fi

if [[ ! "$ssid" =~ ^[[:print:]]{1,32}$ ]]; then
  echo "SSID must contain 1 to 32 printable characters." >&2
  exit 2
fi

read -r -s -p "New Wi-Fi password (8–63 characters): " ap_password
printf '\n'
if [[ ${#ap_password} -lt 8 || ${#ap_password} -gt 63 ]]; then
  unset ap_password
  echo "A WPA2 password must contain 8 to 63 characters." >&2
  exit 2
fi

if ! nmcli -t -f NAME connection show | grep -Fxq "$connection_name"; then
  sudo nmcli connection add type wifi ifname wlan0 con-name "$connection_name" ssid "$ssid" >/dev/null
fi

# Older Raspberry Pi Wi-Fi firmware can fail AP key setup when PMF is optional.
sudo nmcli connection modify "$connection_name" \
  802-11-wireless.ssid "$ssid" \
  802-11-wireless.mode ap \
  802-11-wireless.band bg \
  802-11-wireless.channel 6 \
  802-11-wireless-security.key-mgmt wpa-psk \
  802-11-wireless-security.pmf disable \
  802-11-wireless-security.psk "$ap_password" \
  ipv4.method shared \
  ipv6.method disabled \
  connection.autoconnect yes \
  connection.autoconnect-priority 100
unset ap_password

sudo nmcli connection up "$connection_name" ifname wlan0

echo "Hotspot activated: SSID '$ssid' on wlan0."
echo "Management remains on eth0. Connect a phone to the SSID and use the Wi-Fi password you entered."
