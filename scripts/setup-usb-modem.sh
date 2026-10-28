#!/usr/bin/env bash
# Configure the USB RNDIS mobile router as the boat internet uplink.
set -euo pipefail
if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run with sudo: sudo bash scripts/setup-usb-modem.sh" >&2
  exit 2
fi
interface="usb0"
connection_name="kisero-usb-modem"
if [[ ! -e "/sys/class/net/$interface" ]]; then
  echo "USB network interface $interface is absent; connect the modem first." >&2
  exit 2
fi
if ! nmcli -g connection.id connection show "$connection_name" >/dev/null 2>&1; then
  nmcli connection add type ethernet ifname "$interface" con-name "$connection_name" >/dev/null
fi
nmcli connection modify "$connection_name" \
  connection.interface-name "$interface" \
  connection.autoconnect yes \
  connection.autoconnect-priority 200 \
  connection.autoconnect-retries 0 \
  ipv4.method auto \
  ipv4.never-default no \
  ipv4.route-metric 100 \
  ipv6.method auto \
  ipv6.route-metric 100
# Only the USB connection is activated. Management over eth0 stays available.
nmcli --wait 45 connection up "$connection_name" ifname "$interface"
nmcli -f GENERAL.DEVICE,GENERAL.STATE,IP4.ADDRESS,IP4.GATEWAY device show "$interface"
echo "USB routing configured. SIM registration and APN are managed inside the modem."
