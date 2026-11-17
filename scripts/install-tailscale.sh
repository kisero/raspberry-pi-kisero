#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run this installer with sudo." >&2
  exit 1
fi

if ! dpkg-query -W -f='${Status}\n' tailscale 2>/dev/null | grep -qx 'install ok installed'; then
  . /etc/os-release
  case "$ID" in
    debian|raspbian) distribution=$ID ;;
    *) echo "Unsupported system for this installer: $ID" >&2; exit 1 ;;
  esac
  release_url="https://pkgs.tailscale.com/stable/$distribution/$VERSION_CODENAME"
  staging=$(mktemp -d)
  trap 'rm -f "$staging/keyring.gpg" "$staging/tailscale.list"; rmdir "$staging"' EXIT
  curl -fsSL "$release_url.noarmor.gpg" -o "$staging/keyring.gpg"
  curl -fsSL "$release_url.tailscale-keyring.list" -o "$staging/tailscale.list"
  install -D -m 0644 "$staging/keyring.gpg" /usr/share/keyrings/tailscale-archive-keyring.gpg
  install -D -m 0644 "$staging/tailscale.list" /etc/apt/sources.list.d/tailscale.list
  apt-get update
  apt-get install -y tailscale
fi
systemctl enable --now tailscaled
