#!/usr/bin/env python3
"""Archive Yacht Devices Memory records and publish completed voyages."""
import argparse
import base64
import csv
import hashlib
import io
import ipaddress
import json
import logging
import math
import os
import re
import struct
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener, urlopen
from zoneinfo import ZoneInfo

from boat_tracker import START_DWELL, START_SPEED, STOP_DWELL, STOP_SPEED, connect, post
from pipeline import distance_nm, read_export

LOG = logging.getLogger("kisero-yacht")
LIMIT = 3 * 1024 * 1024
EPOCH = datetime(2015, 1, 1)
KNOTS = 36 / 1852  # cm/s to knots
MEMORY = re.compile(rb"<div\b[^>]*\bid=['\"]D['\"][^>]*>(.*?)</div>.*?</html\s*>", re.I | re.S)
CHANNELS = ("COG", "TWS", "AWS", "TWA", "AWA", "TWD", "Depth", "Heading", "Rudder",
            "STW", "Water Temperature")
CSV_FIELDS = ("Time", "Latitude", "Longitude", "SOG", *CHANNELS, "Memory Record")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def download(url):
    parsed = urlsplit(url)
    address = ipaddress.IPv4Address(parsed.hostname)
    if (parsed.scheme != "http" or parsed.netloc != f"{address}:1458"
            or address not in ipaddress.IPv4Network("10.42.0.0/24")
            or address in (ipaddress.IPv4Address("10.42.0.0"), ipaddress.IPv4Address("10.42.0.1"),
                           ipaddress.IPv4Address("10.42.0.255"))
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise ValueError("Memory URL must point to a gateway on the boat hotspot")
    deadline = time.monotonic() + 300
    raw = bytearray()
    with build_opener(ProxyHandler({}), NoRedirect()).open(url, timeout=25) as response:
        while chunk := response.read1(16384):
            raw.extend(chunk)
            if time.monotonic() > deadline or len(raw) > LIMIT:
                raise ValueError("Memory download exceeded time or size limit")
    return bytes(raw)


def angle(raw):
    return None if raw == 65535 else math.degrees(raw / 10000)


def parse_memory(html):
    match = MEMORY.search(html)
    if not match:
        raise ValueError("incomplete Yacht Devices Memory page")
    points = []
    for encoded in match[1].split():
        block = base64.b64decode(encoded, validate=True)
        offset = 0
        while offset < len(block):
            if len(block) - offset < 32:
                raise ValueError("truncated Memory record")
            flags = block[offset + 31]
            kind, version = flags >> 5, (flags >> 2) & 7
            size = {7: 32, 6: 64, 5: 64, 4: 64}.get(kind)
            if version != 7 or size is None or offset + size > len(block):
                raise ValueError("unsupported or incomplete Memory record")
            record = block[offset:offset + size]
            offset += size
            stamp, lat, lon, cog, sog, awa, aws, twa, tws, heading, stw, depth = (
                struct.unpack_from("<Iii7HhH", record)
            )
            point = {"_time": EPOCH + timedelta(seconds=stamp),
                     "Memory Record": base64.b64encode(record).decode("ascii")}
            if abs(lat) <= 900000000 and abs(lon) <= 1800000000 and (lat or lon):
                point["_latitude"], point["_longitude"] = lat / 1e7, lon / 1e7
            if sog != 65535:
                point["_sog"] = sog * KNOTS
            course, bow, apparent, true = map(angle, (cog, heading, awa, twa))
            wind_reference = bow if bow is not None else course
            values = {
                "COG": course, "Heading": bow,
                "AWA": None if apparent is None else (apparent + 180) % 360 - 180,
                "TWA": None if true is None else (true + 180) % 360 - 180,
                "TWD": None if true is None or wind_reference is None else (wind_reference + true) % 360,
                "AWS": None if aws == 65535 else aws * KNOTS,
                "TWS": None if tws == 65535 else tws * KNOTS,
                "Depth": None if depth == 65535 else depth / 100,
                "STW": None if stw == 32767 else stw * KNOTS,
            }
            if kind == 6:
                values["Water Temperature"] = None if record[49] == 255 else -20 + record[49] / 2
                values["Rudder"] = None if record[52] == 255 else -31.75 + record[52] / 4
            point.update({name: f"{value:.8f}" for name, value in values.items() if value is not None})
            points.append(point)
    if not points:
        raise ValueError("Memory contains no records")
    return sorted(points, key=lambda point: point["_time"])


def csv_bytes(points):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, CSV_FIELDS, delimiter=";")
    writer.writeheader()
    for point in points:
        row = {name: point[name] for name in (*CHANNELS, "Memory Record") if name in point}
        row["Time"] = point["_time"].strftime("%d/%m/%Y, %H:%M:%S")
        for key in ("Latitude", "Longitude", "SOG"):
            row[key] = point.get("_" + key.lower(), "")
        writer.writerow(row)
    return stream.getvalue().encode("utf-8")


def seconds(stamp, zone=timezone.utc):
    return int(stamp.replace(tzinfo=zone).timestamp())


def gps_points(points):
    return [p for p in points if all(key in p for key in ("_latitude", "_longitude", "_sog"))]


def select_outing(points, start, end, interval, zone=timezone.utc):
    unique = {}
    for point in points:
        stamp = seconds(point["_time"], zone)
        if start - interval <= stamp <= end + interval:
            unique[stamp] = point
    times = sorted(unique)
    if len(times) < 2 or times[0] > start + 180 or times[-1] < end - 180:
        raise ValueError("Memory does not cover the GPS outing boundaries")
    if any(right - left >= STOP_DWELL for left, right in zip(times, times[1:])):
        raise ValueError("Memory has a long gap within the GPS outing")
    return [unique[stamp] for stamp in times]


def historical_outings(points):
    outings = []
    candidate = []
    trip = []
    previous = None
    stopped = None

    def finish():
        if trip and trip[-1]["_time"] - trip[0]["_time"] >= timedelta(seconds=STOP_DWELL):
            outings.append(trip.copy())

    for point in points:
        stamp, speed = point["_time"], point["_sog"]
        if previous is not None and stamp <= previous:
            continue
        if previous is not None and (stamp - previous).total_seconds() >= STOP_DWELL:
            finish()
            candidate, trip, stopped = [], [], None
        if not trip:
            if speed >= START_SPEED:
                candidate.append(point)
                if (stamp - candidate[0]["_time"]).total_seconds() >= START_DWELL:
                    trip, candidate = candidate, []
            else:
                candidate = []
        elif speed <= STOP_SPEED:
            if stopped is None:
                stopped = [point]
            else:
                stopped.append(point)
                if (stamp - stopped[0]["_time"]).total_seconds() >= STOP_DWELL:
                    trip.append(stopped[0])
                    finish()
                    trip, stopped = [], None
        else:
            trip.extend(stopped or [])
            trip.append(point)
            stopped = None
        previous = stamp
    return outings


def trip_payload(points, start, zone=timezone.utc):
    track = []
    readings = {}
    for point in points:
        stamp = datetime.fromtimestamp(seconds(point["_time"], zone), timezone.utc)
        timestamp = stamp.strftime("%Y-%m-%dT%H:%M:%S")
        track.append([point["_longitude"], point["_latitude"], timestamp, point["_sog"]])
        row = {("WaterTemperature" if key == "Water Temperature" else key):
               float(point[key].replace(",", ".")) for key in CHANNELS if key != "COG" and point.get(key)}
        row = {key: value for key, value in row.items() if math.isfinite(value)}
        if row:
            readings[timestamp] = row
    speeds = [point[3] for point in track]
    if any(not math.isfinite(value) or value < 0 for value in speeds) or len(track) > 20000:
        raise ValueError("invalid track")
    return {"id": "GPS_" + datetime.fromtimestamp(start, timezone.utc).strftime("%Y%m%dT%H%M%S"),
            "start": track[0][2], "end": track[-1][2], "track": track, "pointCount": len(track),
            "distanceNm": round(sum(distance_nm(a, b) for a, b in zip(points, points[1:])), 2),
            "averageSogKn": round(sum(speeds) / len(speeds), 1), "maxSogKn": round(max(speeds), 1),
            "readings": readings}


def publish(raw, trips):
    answer = post("/v1/ingest", {"rawCsvBase64": base64.b64encode(raw).decode(), "trips": trips})
    if not answer.get("accepted") or answer.get("sha256") != hashlib.sha256(raw).hexdigest():
        raise ValueError("missing upload acknowledgement")


def published_windows():
    api = os.environ["KISERO_API_URL"].rstrip("/")
    with urlopen(api + "/v1/trips", timeout=15) as response:
        trips = json.load(response)["trips"]
    for trip in trips:
        # Legacy manual exports used the browser's Spanish local clock.
        zone = timezone.utc if trip["id"].startswith("GPS_") else ZoneInfo("Europe/Madrid")
        yield tuple(seconds(datetime.fromisoformat(trip[key]), zone) for key in ("start", "end"))


def overlaps(start, end, windows):
    return any(max(start, left) < min(end, right) for left, right in windows)


def backfill(memory, upload):
    points = parse_memory(memory.read_bytes())
    windows = list(published_windows())
    voyages = []
    for group in historical_outings(gps_points(points)):
        start, end = (seconds(point["_time"]) for point in (group[0], group[-1]))
        if overlaps(start, end, windows):
            LOG.info("Skipped already-published interval beginning %s UTC", group[0]["_time"])
            continue
        trip = trip_payload(group, start)
        voyages.append(trip)
        LOG.info("%s through %s UTC, %s points, %.2f nm", trip["start"], trip["end"],
                 trip["pointCount"], trip["distanceNm"])
    if upload:
        raw = csv_bytes(points)
        publish(raw, [])
        for trip in voyages:
            publish(raw, [trip])
            LOG.info("Published %s", trip["id"])
    LOG.info("%s records in snapshot, %s new voyages", len(points), len(voyages))


def collect(url, interval):
    db = connect(os.getenv("KISERO_BOAT_DB", "/var/lib/kisero/boat.sqlite3"))
    pending = db.execute("SELECT started,ended,csv FROM trips WHERE sent=0 AND ended<=? ORDER BY started",
                         (int(time.time()) - interval,)).fetchall()
    if not pending:
        return
    windows = list(published_windows())
    points = None
    for start, end, raw in pending:
        try:
            if not overlaps(start, end, windows):
                if raw is None:
                    if points is None:
                        points = parse_memory(download(url))
                    group = select_outing(gps_points(points), start, end, interval)
                    raw = csv_bytes(group)
                    with db:
                        db.execute("UPDATE trips SET csv=? WHERE started=?", (raw, start))
                    zone = timezone.utc
                else:
                    group = read_export(io.StringIO(raw.decode("utf-8-sig")))
                    # Previously queued downloads were browser-formatted local CSVs.
                    zone = (timezone.utc if "Memory Record" in group[0]
                            else ZoneInfo(os.getenv("KISERO_YACHT_CSV_TIMEZONE", "Europe/Madrid")))
                    group = select_outing(group, start, end, interval, zone)
                trip = trip_payload(group, start, zone)
                publish(raw, [trip])
                windows.append((start, end))
                LOG.info("Published %s", trip["id"])
            with db:
                db.execute("UPDATE trips SET sent=1,csv=NULL WHERE started=?", (start,))
        except Exception as error:
            LOG.warning("Trip beginning %s UTC still queued (%s: %s)",
                        datetime.fromtimestamp(start, timezone.utc), type(error).__name__, error)


def main():
    from pathlib import Path
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backfill", type=Path, metavar="MEMORY_HTML")
    parser.add_argument("--publish", action="store_true", help="Upload the backfill through the existing API")
    args = parser.parse_args()
    if args.publish and not args.backfill:
        parser.error("--publish requires --backfill")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.backfill:
        backfill(args.backfill, args.publish)
    elif url := os.getenv("KISERO_YACHT_MEMORY_URL"):
        interval = int(os.getenv("KISERO_YACHT_SAMPLE_SECONDS", "15"))
        if not 1 <= interval <= 300:
            raise ValueError("Yacht Devices logging interval must be 1–300 seconds")
        collect(url, interval)


if __name__ == "__main__":
    main()
