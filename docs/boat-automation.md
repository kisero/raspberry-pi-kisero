# Boat GPS, voyage imports, and OwnTracks

## USB GPS and boat status

The installed USB u-blox 7 receiver is detected under
`/dev/serial/by-id/usb-u-blox*`. Set `KISERO_GPS_DEVICE` in
`/etc/kisero/boat.env` if more than one receiver matches. Install the tracker
with `sudo bash scripts/install-boat-services.sh` after deploying AWS and
preparing the device environment files. See the [README](../README.md).

The tracker confirms departure at 1 knot or more for 60 seconds and arrival
at 0.5 knots or less for 10 minutes. It records the times at which those
periods began. The voyage queue survives restarts. The public website shows
Moored or Sailing and a named area when the position falls in a configured
coverage area. These speed thresholds cover movement under sail or motor.

## Yacht Devices Memory server

The YDWG-02 gateway joins `Kisero-Boat` in Wi-Fi Client mode. The working
hotspot address is `10.42.0.149`. If DHCP changes it, update
`KISERO_YACHT_MEMORY_URL` in `/etc/kisero/boat.env`. Configure a
stable address before relying on unattended access after a gateway reset.

Set Server #3 to **Memory** on TCP port **1458**. The live gateway uses a
15-second interval, NMEA 2000 Only, the Sailing Yacht data set, and the
five-metre minimum spacing option. Its current download range is All data.
The Pi can fetch the Memory page directly at `http://10.42.0.149:1458/`.
The firmware sends binary records encoded in the page. The Pi decodes
those records to CSV with UTC timestamps.

A timer retries completed outings until it can match the gateway data to
the USB GPS boundaries. If a download has missing blocks, the collector
takes a second snapshot and merges the available records. A valid export
is queued before AWS is contacted. Leave the gateway powered long enough
after arrival for the stop confirmation and import, or let the timer
retry when the gateway is available again. The gateway overwrites its
oldest stored records when memory fills, so keep the private archive.

### Historical backfill

Save the raw Memory pages privately. With `KISERO_API_URL` configured,
preview the inferred voyages using one or more snapshots.

```sh
python3 collector/yacht_fetch.py --backfill /path/to/memory.html /path/to/second-memory.html
```

With the device upload environment, add `--publish` to archive the
merged records in private S3 and update the public Sailing Log. Review
the preview before using this option. A later snapshot can improve an
already imported track with the same boundaries and more points.
The original historical CSV workflow remains available through
[`pipeline.py`](../collector/pipeline.py) and [`uploader.py`](../collector/uploader.py).

Reference for the gateway setup [YDWG-02 manual, Memory mode](https://www.yachtd.com/downloads/ydwg02.pdf#page=41).

## OwnTracks for iPhone

Select HTTP mode, use the HTTPS API base plus `/v1/alarm/owntracks`,
username `kisero`, and the dedicated OwnTracks password. That password is
the lowercase hex HMAC-SHA256 of `kisero-owntracks-v1`, using the existing
Pi device token as the key. Keep it private.

Allow Always and Precise Location in iOS. Use Move mode and send a manual
position to verify receipt. The private alarm page can show distance to the
boat when both fixes are recent. Set Auto only after verifying that the boat
and phone positions are arriving. Manual On and Manual Off can override Auto.
Fresh fixes and the accuracy margin around 300 m are described in the [README](../README.md).
