# Boat GPS, voyages, and alarm

Install the GPS tracker and voyage upload timer on the Pi with `sudo scripts/install-boat-services.sh` after deploying the AWS SAM stack. The tracker reuses `/etc/kisero/sensor.env` for the API URL and device token. The USB u-blox is detected by its persistent serial name. Set `KISERO_GPS_DEVICE` in `/etc/kisero/boat.env` if multiple receivers match.

A valid GPS fix is required. The tracker confirms departure at 1 knot or more for 60 seconds, and arrival at 0.5 knots or less for 10 minutes. It records the time each period began. An active outing and completed upload jobs survive Pi restarts. The website shows the nearest configured area and reports when the live position is unavailable.

## Yacht Devices export

The upload timer waits for a validated Memory CSV endpoint on the hotspot. Confirm the gateway joins the hotspot at 10.42.0.2 and inspect the Memory server to determine how its CSV is exported. If the firmware serves CSV at a direct path, set these values in `/etc/kisero/boat.env`:

- `KISERO_YACHT_CSV_URL` is the verified HTTP URL on `10.42.0.2:1458`.
- `KISERO_YACHT_CSV_TIMEZONE` is the timezone used in the exported timestamps, such as `UTC` if confirmed.
- `KISERO_YACHT_SAMPLE_SECONDS` is the logging interval, currently assumed to be 15 seconds.

Only the completed outing's samples and sailing readings are published. The original CSV is archived privately. If an export is incomplete or the service is offline, the outing stays queued for the timer to retry. A firmware version that only constructs CSV in the browser needs a downloader for its underlying log format.

## OwnTracks for iPhone

Select HTTP mode, use the HTTPS API base plus `/v1/alarm/owntracks`, username `kisero`, and the dedicated OwnTracks password. That password is the lowercase hex HMAC-SHA256 of `kisero-owntracks-v1` using the existing Pi device token as the key. Keep it out of Git and the website.

Allow Always and Precise location in iOS. Use Move mode and send one position manually to verify setup. Keep the alarm in manual mode during the first check. The alarm page can then switch between Manual On, Manual Off, and Auto. The backend uses fresh positions and accounts for GPS accuracy near the 300 metre boundary. If a fix is stale or uncertain it keeps the last alarm state. An underway boat disarms in Auto. Only the private backend receives phone coordinates.
