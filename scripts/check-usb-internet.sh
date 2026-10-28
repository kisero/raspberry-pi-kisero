#!/usr/bin/env bash
# HTTPS is deliberately bound to the modem: Ethernet must not mask a failure.
set -euo pipefail
interface="usb0"
ip -brief address show "$interface"
ip route show default dev "$interface"
status="$(curl --interface "$interface" --connect-timeout 8 --max-time 20 \
  --fail --silent --show-error --output /dev/null --write-out '%{http_code}' \
  https://www.google.com/generate_204)"
if [[ "$status" != 204 ]]; then
  echo "Unexpected connectivity-check response: HTTP $status" >&2
  exit 1
fi
echo "USB mobile internet: HTTPS succeeded (HTTP 204)."
