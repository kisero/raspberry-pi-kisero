# Kisero Raspberry Pi

This repository is the source of truth for the boat Raspberry Pi setup and application.

See [WIRING.md](WIRING.md) for the latest physical pin numbers, cable colors,
breadboard holes, and verification status for the buzzer, motion sensor, and
temperature sensor. The GPS is not yet connected.

## Current network design

- `eth0` is the home-router management and internet link whenever the cable is connected (DHCP, route metric 50).
- `wlan0` is the boat Wi-Fi access point for the Yachtdevice and phone. It is configured as `Kisero-Boat` on 2.4 GHz channel 6.
- NetworkManager's `shared` mode provides DHCP and routes hotspot clients through the current internet uplink. At home this is Ethernet; aboard it is the USB 4G modem (route metric 100), whose HTTPS connectivity has been verified.
- The Yachtdevice should join the Pi access point in Wi-Fi Client mode. Reserve its address on the Pi before enabling the log collector.

The Pi 3's built-in Wi-Fi required Protected Management Frames (PMF) to be disabled for WPA-PSK access point startup on this Debian 13 image. The hotspot remains password-protected; the setup script applies this compatibility setting.

## Current status (2026-10-28)

- Hotspot remains active as `Kisero-Boat`, with subnet `10.42.0.0/24` and Pi address `10.42.0.1`.
- Ethernet management uses the dedicated `kisero-home-ethernet` NetworkManager profile, bound to `eth0`, with DHCP and autoconnect enabled. Its last verified home-network address is `192.168.68.68/22` (router `192.168.68.1`). SSH was last verified as `admin@192.168.68.68` without joining the hotspot.
- The Ethernet MAC address observed on the Pi is **`b8:27:eb:23:e8:89`**. Use this address for a router DHCP reservation; `b8:27:eb:76:bd:dc` is the Wi-Fi MAC, not the Ethernet MAC. DHCP may change the IP unless the router reserves it.
- The 4G UFI USB modem presents an RNDIS network adapter as `usb0` at `192.168.100.158/24`. The existing generic `netplan-eth0` profile was attached to that adapter, leaving physical Ethernet disconnected even with carrier detected. The dedicated Ethernet profile fixes this without altering the USB or hotspot profiles.
- Home Ethernet is preferred while connected (metric 50); the USB modem is the default internet uplink aboard when Ethernet is absent (metric 100).
- The Yachtdevice collector still needs live-device export inspection aboard before automated downloads can be enabled.

To recreate or repair the wired management profile, copy and run `scripts/setup-ethernet.sh` on the Pi with `sudo bash scripts/setup-ethernet.sh`. It activates DHCP on `eth0` and persists across reboots; it does not restart NetworkManager or alter `wlan0`.

## Yachtdevice log collection

See [ARCHITECTURE.md](ARCHITECTURE.md) for the recommended low-maintenance AWS
archive, public track site, collection cadence, cost drivers, and implementation
sequence.

The Yacht Devices YDWG-02 manual (firmware 1.71) documents recorded-data export
through its browser export page. To make it available to the Pi:

1. Reserve `10.42.0.2` for the Yachtdevice, or exclude it from the hotspot DHCP
   allocation range before using it as a static address. This reservation is still
   pending until the device is available aboard. Then join the Yachtdevice to
   `Kisero-Boat` in Wi-Fi Client mode, using `10.42.0.2/24`, gateway and DNS
   `10.42.0.1`.
2. In the Yachtdevice NMEA Servers settings, set Server #3's data protocol to
   `Memory` and its port to `1458`.
3. The export page is then at `http://10.42.0.2:1458/` and can export recorded
   points as CSV, GPX, or XML.

The manual describes the export as a browser workflow: the page first loads the
stored data, then presents format and export options. It does not document a
direct file-download URL or a stable machine API. Inspect the live page and
download request before implementing automated collection. Keep raw exports
append-only and outside Git; do not overwrite older logs.

The supplied example export is a semicolon-separated CSV with a UTF-8 BOM,
quoted timestamps in `DD/MM/YYYY, HH:MM:SS` format, and columns for position,
depth, speed over ground, wind, heading, and other measurements. Parse it with
that locale and preserve the original export as the source record. Trip
detection will use the requested definition of any time moving underway, not a
claim that the boat was specifically under sail. The sample has no engine
state, so it cannot distinguish sailing from motoring. Calibrate configurable
speed/duration thresholds against actual passages.

The manual says factory logging is enabled at a five-minute interval and that
device memory overwrites old points when full. Set up recurring collection and
verify retention onboard before relying on the Pi as a backup. The requested
archive is AWS S3 and kisero.org will show exact tracks publicly; raw CSV sensor
exports remain private by default. Keep upload credentials in a device-only
secrets file, never in this repository.

## Collector prototype and local simulation

The supplied export parser and configurable underway detector are in
`collector/pipeline.py`. Run a private local simulation (replace the source
path as needed):

```sh
python3 collector/pipeline.py "/path/to/Yachtdevice export.csv" --output /tmp/kisero-derived
```

It writes a trip index and exact-track JSON into the chosen output directory.
Those files contain precise locations; keep them out of Git and share them only
with the intended audience. The default detector uses SOG >= 1 knot, a 20-minute
gap to join moving intervals, and a 10-minute minimum duration. These are
starting values to tune against real onboard logs.

`collector/uploader.py` queues an explicitly selected CSV in a private local
SQLite database, then sends pending exports and their derived tracks to the
API. It removes an item from the retry queue only after AWS acknowledges the
matching SHA-256 digest. The database defaults to `var/collector.db` (ignored
by Git, mode 0600) and can be moved with `KISERO_QUEUE_PATH`. It requires
`KISERO_API_URL` and `KISERO_DEVICE_TOKEN` in its runtime environment. It does
not yet poll the Yachtdevice: its documented export is a browser workflow, so
inspect the live unit's download requests aboard before automating acquisition
or scheduling uploads.

The SAM template under `aws/` creates a private, encrypted, versioned S3
archive and a Lambda-backed API. Anonymous GET routes serve the published exact
tracks and the recent cabin temperature/humidity series; authenticated Pi POST
routes archive raw NMEA exports and sensor samples. The API token is held in an
SSM SecureString.

Hotspot setup is performed with `scripts/setup-hotspot.sh`. It prompts for the Wi-Fi password and does not put it in this repository. Do not commit Wi-Fi passwords, modem credentials, private keys, or raw NMEA/position logs.

## Device baseline

- Raspberry Pi 3 Model B Rev 1.2, Debian GNU/Linux 13.7 (checked 2026-10-15).
- Wi-Fi access point configuration is managed by NetworkManager.

## Temperature and humidity sensor

The SHT3x breakout uses I²C. The latest breadboard wiring and the missing
soldered-header requirement are recorded in [WIRING.md](WIRING.md). VIN uses
3.3 V, SDA uses physical pin 3, and SCL uses physical pin 5. Enable the Pi's standard I²C
interface with `scripts/enable-i2c.sh`; a reboot is required before checking
for the sensor at address `0x44` or `0x45`.

`collector/sensor_collector.py` validates the SHT3x CRC, samples the sensor,
queues each reading locally until AWS acknowledges it, and posts readings to
`/v1/sensors`. Run it with `--check` to take a read-only sample without queueing
or uploading it. `systemd/kisero-sensor.timer` runs the oneshot service five
minutes after the previous run. Install the service files from the repository
at `/opt/kisero`; create `/etc/kisero/sensor.env` with `KISERO_API_URL` and
`KISERO_DEVICE_TOKEN` (mode 0600, never in Git), then enable
`kisero-sensor.timer`. The API keeps the complete encrypted sensor archive
private in S3 and exposes only the recent temperature/humidity series to the
website.

## USB 4G modem (2026-10-28)

The connected stick enumerates as USB `05c6:9024` (Qualcomm Android) and exposes
`usb0` through the Linux `rndis_host` driver. It is a self-contained mobile router:
the SIM, carrier registration, and APN are handled by its 4G UFI web interface at
`http://192.168.100.1/`, rather than ModemManager on the Pi.

`scripts/setup-usb-modem.sh` creates the persistent `kisero-usb-modem` profile
bound only to `usb0`, using DHCP, autoconnect, and route metric 100. Run it with
sudo on the Pi. The home Ethernet profile uses metric 50, so Ethernet supplies
internet while attached; USB supplies the default route when Ethernet is absent.
The existing hotspot uses NetworkManager shared mode to route boat clients via
the available uplink. No NetworkManager restart is required.

Run `scripts/check-usb-internet.sh` to check HTTPS explicitly through `usb0`.
Success through home Ethernet is not evidence that the SIM has working data.

`scripts/modem-status.py --login` prompts for the modem web password and prints
SIM/network/APN status with credentials and SIM identifiers redacted. An authenticated
session is held privately under `/run/user/<uid>/` for the current boot; credentials
are not stored in Git. It also supports `--select-sim 1` or `--select-sim 2` for this
modem's two selectable slots. Selecting a slot may briefly restart the modem.

Initial diagnosis before the SIM was reseated/unlocked: USB DHCP and modem administration worked, but both SIM selections
reported `simCardState=invalid`, no SIM identifiers, no service, no WAN IP, and APN
`none`. USB-bound traffic received “Destination Net Unreachable” from the modem.
Selection was returned to slot 1. After the user addressed the physical SIM/PIN,
the modem reported `simCardState=ok`, carrier `MASMOVIL`, and a connected mobile WAN.
It automatically selected its `Yoigo Internet` profile with APN `internet`.
A USB-bound Google HTTPS check returned HTTP 204, and the Kisero AWS `/v1/sensors` endpoint returned HTTP 200 over USB, independently of Ethernet.
The diagnostic uses this endpoint because example.com reset connections on this
mobile service; ICMP and direct Cloudflare tests did not succeed. No manual APN
change or SIM PIN guessing was needed. Network time synchronization is now active.

## Reproducing the configuration

The setup scripts are the reproducible, non-secret configuration record. Raw
NetworkManager connection files, modem session files, and runtime environment
files must not be committed: they can contain passwords or upload tokens.

| Component | Repository record | Device configuration |
| --- | --- | --- |
| Home Ethernet | `scripts/setup-ethernet.sh` | `kisero-home-ethernet`, bound to `eth0`, DHCP, autoconnect, metric 50 |
| USB mobile uplink | `scripts/setup-usb-modem.sh` | `kisero-usb-modem`, bound to `usb0`, DHCP, autoconnect, metric 100 |
| Boat Wi-Fi | `scripts/setup-hotspot.sh` | `kisero-boat-ap`, `Kisero-Boat`, 2.4 GHz channel 6, WPA2, PMF disabled, shared IPv4 |
| Cabin sensor | `scripts/enable-i2c.sh`, `scripts/install-sensor-service.sh`, `systemd/kisero-sensor.*` | I²C SHT3x at `0x44`/`0x45`, five-minute collection and queued upload |
| Cloud infrastructure | `aws/template.yaml` | SAM/CloudFormation stack `kisero-yachtdevice`, region `eu-north-1` |
| Modem diagnostics | `scripts/modem-status.py`, `scripts/check-usb-internet.sh` | Redacted modem status and USB-bound HTTPS checks |

For a replacement Pi, apply the Ethernet and USB scripts, then configure the
hotspot over Ethernet using its existing script. Enter a Wi-Fi password at the
prompt; recreate `/etc/kisero/sensor.env` privately and install the sensor service.
SIM subscription and PIN policy are configured on the SIM/modem, outside Git.
The modem selected SIM slot 1 and APN `internet` automatically; no operator account
password, SIM PIN, IMEI, IMSI, ICCID, or modem web password is saved here.

Confirmed on 2026-10-28: Ethernet SSH, active hotspot, USB-bound HTTPS (HTTP 204),
Kisero AWS access over USB (HTTP 200), enabled modem autoconnect, active sensor
timer, and synchronized system time. A physical cable-removal/reboot failover
check and testing with the Yachtdevice/Raymarine aboard remain outstanding.
