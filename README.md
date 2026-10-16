# Kisero Raspberry Pi

This repository is the source of truth for the boat Raspberry Pi setup and application.

## Current network design

- `eth0` is the temporary home-router management and internet link while the hotspot is configured.
- `wlan0` is the boat Wi-Fi access point for the Yachtdevice and phone. It is configured as `Kisero-Boat` on 2.4 GHz channel 6.
- NetworkManager's `shared` mode provides DHCP and routes hotspot clients through the current internet uplink. At home this is Ethernet; aboard it will be the supported USB 4G modem.
- The Yachtdevice should join the Pi access point in Wi-Fi Client mode. Reserve its address on the Pi before enabling the log collector.

The Pi 3's built-in Wi-Fi required Protected Management Frames (PMF) to be disabled for WPA-PSK access point startup on this Debian 13 image. The hotspot remains password-protected; the setup script applies this compatibility setting.

## Current status (2026-10-15)

- Hotspot is active, with NetworkManager shared subnet `10.42.0.0/24` and Pi address `10.42.0.1`.
- Ethernet management and internet are active through `eth0`; hotspot NAT is installed. The user confirmed their phone connects successfully to the hotspot.
- The Yachtdevice and 4G modem have not been connected/configured yet.

## Yachtdevice log collection

See [ARCHITECTURE.md](ARCHITECTURE.md) for the recommended low-maintenance AWS
archive, public track site, collection cadence, cost drivers, and implementation
sequence.

The Yacht Devices YDWG-02 manual (firmware 1.71) documents recorded-data export
through its browser export page. To make it available to the Pi:

1. Join the Yachtdevice to `Kisero-Boat` in Wi-Fi Client mode and set its static
   address to `10.42.0.2/24` (Pi gateway `10.42.0.1`).
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

The SHT3x breakout uses I²C. Connect VIN to Pi 3.3 V, GND to ground, SDA to
physical pin 3, and SCL to physical pin 5. Enable the Pi's standard I²C
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
