#!/usr/bin/env bash
# Give the physical Ethernet socket its own persistent DHCP connection.
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run with sudo: sudo bash scripts/setup-ethernet.sh" >&2
  exit 2
fi

connection_name="kisero-home-ethernet"
interface="eth0"
if [[ ! -e "/sys/class/net/$interface/address" ]]; then
  echo "Physical Ethernet interface $interface was not found." >&2
  exit 2
fi

if ! nmcli -g connection.id connection show "$connection_name" >/dev/null 2>&1; then
  nmcli connection add type ethernet ifname "$interface" con-name "$connection_name" >/dev/null
fi

# Bind only this profile to eth0. Do not modify USB or Wi-Fi profiles.
# Home Ethernet is preferred while attached; USB metric 100 takes over aboard.
nmcli connection modify "$connection_name" \
  connection.interface-name "$interface" \
  connection.autoconnect yes \
  connection.autoconnect-priority 100 \
  ipv4.method auto \
  ipv4.never-default no \
  ipv4.route-metric 50 \
  ipv6.method auto \
  ipv6.route-metric 50

nmcli --wait 45 connection up "$connection_name" ifname "$interface"
nmcli -f GENERAL.DEVICE,GENERAL.HWADDR,GENERAL.STATE,IP4.ADDRESS,IP4.GATEWAY device show "$interface"
