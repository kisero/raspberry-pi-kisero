#!/usr/bin/env python3
"""Fetch an explicitly verified local Memory CSV path and publish queued outings."""
import base64
import hashlib
import logging
import math
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener
from zoneinfo import ZoneInfo

from boat_tracker import connect, post
from pipeline import distance_nm, parse_export

LOG = logging.getLogger("kisero-yacht")
LIMIT = 3 * 1024 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def download(url):
    parsed = urlsplit(url)
    if parsed.scheme != "http" or parsed.netloc != "10.42.0.2:1458":
        raise ValueError("export URL must point to the local Yacht Devices Memory server")
    with build_opener(ProxyHandler({}), NoRedirect()).open(url, timeout=20) as response:
        raw = response.read(LIMIT + 1)
    if not raw or len(raw) > LIMIT:
        raise ValueError("invalid export size")
    return raw


def trip_for(raw, start, end, zone, interval):
    with tempfile.TemporaryDirectory(prefix="kisero-yacht-") as folder:
        path = Path(folder) / "export.csv"
        path.write_bytes(raw)
        points = parse_export(path)
    def seconds(p):
        return p["_time"].replace(tzinfo=zone).timestamp()
    if not points or seconds(points[-1]) < end - interval:
        raise ValueError("export does not yet cover the trip end")
    unique = {seconds(p): p for p in points if start-interval <= seconds(p) <= end+interval}
    if len(unique) < 2 or min(unique) > start+interval or max(unique) < end-interval:
        raise ValueError("export does not cover the outing")
    ordered = sorted(unique.items())
    group = [p for _, p in ordered]
    track = [[p["_longitude"], p["_latitude"], datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds").removesuffix("+00:00"), p["_sog"]] for t,p in ordered]
    speed = [point[3] for point in track]
    if any(not math.isfinite(v) or v < 0 for v in speed) or len(track) > 20000:
        raise ValueError("invalid track")
    channels = ("TWS", "AWS", "TWA", "AWA", "TWD", "Depth", "Heading", "Rudder", "STW", "Water Temperature")
    readings = {}
    for (_, point), coords in zip(ordered, track):
        row = {}
        for key in channels:
            try:
                value = float(point.get(key, "").replace(",", "."))
                if math.isfinite(value):
                    row["WaterTemperature" if key == "Water Temperature" else key] = value
            except ValueError:
                pass
        if row:
            readings[coords[2]] = row
    return {"id": "GPS_" + datetime.fromtimestamp(start, timezone.utc).strftime("%Y%m%dT%H%M%S"),
            "start": track[0][2], "end": track[-1][2], "track": track, "pointCount": len(track),
            "distanceNm": round(sum(distance_nm(a,b) for a,b in zip(group,group[1:])),2),
            "averageSogKn": round(sum(speed)/len(speed),1), "maxSogKn": round(max(speed),1),
            "readings": readings}


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    url = os.getenv("KISERO_YACHT_CSV_URL")
    if not url:
        return
    zone = ZoneInfo(os.environ["KISERO_YACHT_CSV_TIMEZONE"])
    interval = int(os.getenv("KISERO_YACHT_SAMPLE_SECONDS", "15"))
    if not 1 <= interval <= 300:
        raise ValueError("Yacht Devices logging interval must be 1–300 seconds")
    db = connect(os.getenv("KISERO_BOAT_DB", "/var/lib/kisero/boat.sqlite3"))
    now = int(time.time())
    raw_this_run = None
    for start,end,raw in db.execute("SELECT started,ended,csv FROM trips WHERE sent=0 AND ended<=? ORDER BY started", (now-interval,)).fetchall():
        try:
            if raw is None:
                if raw_this_run is None:
                    raw_this_run = download(url)
                trip = trip_for(raw_this_run, start, end, zone, interval)
                raw = raw_this_run
                with db:
                    db.execute("UPDATE trips SET csv=? WHERE started=?", (raw,start))
            else:
                trip = trip_for(raw, start, end, zone, interval)
            answer = post("/v1/ingest", {"rawCsvBase64": base64.b64encode(raw).decode(), "trips": [trip]})
            if not answer.get("accepted") or answer.get("sha256") != hashlib.sha256(raw).hexdigest():
                raise ValueError("missing upload acknowledgement")
            with db:
                db.execute("UPDATE trips SET sent=1,csv=NULL WHERE started=?", (start,))
            LOG.info("Published %s", trip["id"])
        except Exception as error:
            LOG.warning("Trip still queued (%s)", type(error).__name__)


if __name__ == "__main__":
    main()
