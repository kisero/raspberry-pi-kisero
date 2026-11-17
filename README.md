# Kisero Raspberry Pi

The onboard Pi runs the `Kisero-Boat` Wi-Fi hotspot, shares the boat's 4G
connection, monitors the cabin and alarm, and publishes sailing tracks from
the Yacht Devices NMEA 2000 gateway. The website reads the AWS API at runtime.

- [Live site](https://kisero.org/) and [website repository](https://github.com/kisero/kisero.org)
- [Wiring and GPIO assignments](WIRING.md)
- [Tailscale remote access](docs/remote-access.md)
- [GPS, voyage imports, and OwnTracks](docs/boat-automation.md)
- [Data flow and storage](ARCHITECTURE.md) and [AWS deployment](aws/DEPLOYMENT.md)

## Onboard setup

Verified on 17 November 2026 on a Raspberry Pi 3 Model B Rev 1.2 running
Debian 13.7. The boat's hotspot, 4G default route, and remote SSH worked with
Ethernet disconnected. The cabin sensor returned a valid reading at `0x70`,
the USB GPS and installed services were present, and the Yacht Devices Memory
download and historical import worked. The first automatic publishing run
from a new completed outing is still to be verified.

| Component | Current configuration | Setup or operations |
| --- | --- | --- |
| Wi-Fi hotspot | `Kisero-Boat` on `wlan0`, 2.4 GHz channel 6, Pi at `10.42.0.1/24` | [setup-hotspot.sh](scripts/setup-hotspot.sh) |
| 4G uplink | UFI modem at `192.168.100.1`, `kisero-usb-modem` on RNDIS `usb0`, DHCP metric 100 | [setup-usb-modem.sh](scripts/setup-usb-modem.sh), [check-usb-internet.sh](scripts/check-usb-internet.sh) |
| Wired recovery | `kisero-home-ethernet` on `eth0`, DHCP metric 50. The router assigns its LAN address. | [setup-ethernet.sh](scripts/setup-ethernet.sh) |
| Remote SSH | `tailscale ssh admin@kisero-boat` from the same personal tailnet | [Remote access](docs/remote-access.md) |
| Boat GPS | USB u-blox 7 receiver, detected through `/dev/serial/by-id/` | [Boat automation](docs/boat-automation.md) |
| Yacht Devices gateway | Wi-Fi client at `10.42.0.149` as verified aboard, firmware 1.60, Memory server on TCP 1458 | [Boat automation](docs/boat-automation.md) |
| Cabin sensor | SHTC3 at I²C address `0x70`, sampled every five minutes | [Wiring](WIRING.md), [install-sensor-service.sh](scripts/install-sensor-service.sh) |
| Motion alarm | PIR on BCM26 (physical 37), buzzer on BCM18 (physical 12) | [Wiring](WIRING.md), [install-alarm-service.sh](scripts/install-alarm-service.sh) |

NetworkManager shared mode routes hotspot clients through the current uplink.
Ethernet takes priority when connected. The hotspot setup prompts for its WPA2
password and disables PMF for compatibility with the Pi's built-in Wi-Fi.
Manage the modem's SIM and APN in the modem's local UI. The last verified modem
configuration used SIM slot 1 and APN `internet`, selected by the modem.
[modem-status.py](scripts/modem-status.py) can report its connection status with
credentials and SIM identifiers redacted.

## Running services

| Unit | Job |
| --- | --- |
| `kisero-boat.service` | Reads USB GPS continuously, attempts to send a fresh fix every 15 seconds, and saves voyage boundaries in SQLite. |
| `kisero-yacht.timer` | Checks for completed voyages about every three minutes after the previous run. Downloads the Memory log, queues the export locally, and publishes the track after verification. |
| `kisero-sensor.timer` | Samples cabin temperature and humidity every five minutes and retries queued uploads. |
| `kisero-alarm.service` | Monitors motion, operates the buzzer locally, reads alarm controls, and sends Pi contact updates about every 30 seconds while online. |

The public site shows Moored or Sailing with the named area when available,
the Sailing Log with GPS tracks and wind readings, and cabin, alarm activity,
and internet-contact charts with Today, Last Week, and Last Month views.
The homepage opens with a [cached snapshot](ARCHITECTURE.md#homepage-snapshot)
and checks for updates every 15 seconds while visible. It shows the boat offline
after 60 seconds without an AWS-received Pi heartbeat, with the last readings
and contact time visible.
The public location label uses a named area. Exact tracks and timestamps are
published for completed outings. Live boat and phone fixes for Auto alarm
control stay private.

### Alarm

The private alarm page supports Manual On, Manual Off, and Auto. Auto uses the
distance between the boat GPS and the owner's OwnTracks phone fix. It arms
when the boat is moored and the phone is confidently beyond 300 m, and
disarms when the phone is confidently within that range or the boat is
underway. Stale or uncertain positions leave the existing setting in place.

The PIR has a 60-second warm-up. Arming gives a 30-second exit delay, and an
armed trigger pulses the buzzer for 10 seconds. The Pi retains the last applied
setting through network loss and queues events locally. AWS sends an email
to the confirmed SNS subscriber when it receives an armed trigger. The website's alarm timeline
highlights armed activity. Generate the private control link on the Pi with
`sudo python3 scripts/alarm-control-url.py` from the repository checkout.
Keep the full link private.

## Restoring the Pi

1. Set up or verify the [AWS stack](aws/DEPLOYMENT.md). Keep the existing stack
   and bucket when restoring a Pi.
2. Use the Ethernet, modem, hotspot, and Tailscale scripts linked above as
   needed. Join the gateway to the hotspot as a Wi-Fi client and verify its IP
   before configuring the importer. Set Server #3 to Memory on port 1458.
3. Install the system packages `python3-smbus2`, `python3-gpiozero`, and
   `python3-lgpio`. Enable I²C with [enable-i2c.sh](scripts/enable-i2c.sh) and
   reboot before testing the cabin sensor.
4. Create root-owned mode-0600 files in `/etc/kisero/` from
   [sensor.env.example](config/sensor.env.example) and
   [boat.env.example](config/boat.env.example). Fill in the API URL and device
   token privately. Set the Memory URL to the gateway's current address.
5. Run the three installers from the checkout.

   ```sh
   sudo bash scripts/install-sensor-service.sh
   sudo bash scripts/install-alarm-service.sh
   sudo bash scripts/install-boat-services.sh
   ```

6. Verify the services and a local cabin reading on the Pi.

   ```sh
   systemctl is-active kisero-boat.service kisero-alarm.service kisero-sensor.timer kisero-yacht.timer
   python3 /opt/kisero/collector/sensor_collector.py --check
   bash scripts/check-usb-internet.sh
   ```

The live SQLite queues and alarm state are under `/var/lib/kisero/`. Keep
them during upgrades. Keep raw logs, runtime configuration, and credentials
out of Git. For a manual Memory backfill, see the [boat automation runbook](docs/boat-automation.md).
Run the collector tests locally with `PYTHONPATH=collector python3 -m unittest discover -s tests`.
