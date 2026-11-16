#!/usr/bin/env python3
"""Read the USB GPS continuously; persist trip boundaries and send current state."""
import glob
import json
import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

LOG = logging.getLogger("kisero-boat")
START_SPEED, STOP_SPEED, START_DWELL, STOP_DWELL = 1.0, 0.5, 60, 600


def position(line):
    body, sep, check = line.strip().rpartition(b"*")
    if not sep or not body.startswith(b"$") or len(check) != 2:
        return None
    checksum = 0
    for value in body[1:]:
        checksum ^= value
    if f"{checksum:02X}".encode() != check.upper():
        return None
    try:
        row = body.decode("ascii").split(",")
        if not row[0].endswith("RMC") or row[2] != "A" or row[4] not in ("N", "S") or row[6] not in ("E", "W"):
            return None
        def axis(raw, hemi):
            value = float(raw)
            degrees, minutes = divmod(value, 100)
            if value < 0 or not 0 <= minutes < 60:
                raise ValueError()
            return (degrees + minutes / 60) * (-1 if hemi in ("S", "W") else 1)
        lat, lon, speed = axis(row[3], row[4]), axis(row[5], row[6]), float(row[7])
        stamp = datetime.strptime(row[9] + row[1].split(".")[0], "%d%m%y%H%M%S").replace(tzinfo=timezone.utc).timestamp()
        if not (-90 <= lat <= 90 and -180 <= lon <= 180 and 0 <= speed <= 80):
            return None
        return {"lat": lat, "lon": lon, "speed": speed, "tst": stamp}
    except (ValueError, IndexError, UnicodeError):
        return None


def connect(path):
    db = sqlite3.connect(path, timeout=5)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE IF NOT EXISTS tracker (id INTEGER PRIMARY KEY, started INTEGER)")
    db.execute("CREATE TABLE IF NOT EXISTS trips (started INTEGER PRIMARY KEY, ended INTEGER NOT NULL, csv BLOB, sent INTEGER NOT NULL DEFAULT 0)")
    return db


class Movement:
    def __init__(self, db):
        self.db = db
        row = db.execute("SELECT started FROM tracker WHERE id=1").fetchone()
        self.started = row[0] if row else None
        self.candidate = None
        self.still_since = None
        self.previous = None
        self.state = "sailing" if self.started else "unknown"

    def observe(self, fix):
        t, speed = int(fix["tst"]), fix["speed"]
        if self.previous is not None and t <= self.previous:
            return
        if self.previous is None or t - self.previous > 10:
            self.candidate = self.still_since = None
            if self.started is None:
                self.state = "unknown"
        self.previous = t
        changing = speed >= START_SPEED if self.started is None else speed <= STOP_SPEED
        if changing:
            self.still_since = None
            if self.candidate is None:
                self.candidate = t
            if self.started is None and t - self.candidate >= START_DWELL:
                self.started = self.candidate
                with self.db:
                    self.db.execute("INSERT OR REPLACE INTO tracker VALUES (1,?)", (self.started,))
                self.state, self.candidate = "sailing", None
                LOG.info("Underway confirmed")
            elif self.started is not None and t - self.candidate >= STOP_DWELL:
                with self.db:
                    self.db.execute("INSERT OR IGNORE INTO trips(started,ended) VALUES (?,?)", (self.started,self.candidate))
                    self.db.execute("DELETE FROM tracker WHERE id=1")
                self.started, self.candidate, self.state = None, None, "moored"
                LOG.info("Trip complete; Yacht Devices export queued")
            elif self.started is None:
                self.state = "unknown"
        else:
            self.candidate = None
            if self.started is None:
                if speed > STOP_SPEED:
                    self.still_since, self.state = None, "unknown"
                else:
                    if self.still_since is None:
                        self.still_since = t
                    if t - self.still_since >= START_DWELL:
                        self.state = "moored"


def serial_fixes():
    import select
    import termios
    configured = os.getenv("KISERO_GPS_DEVICE")
    devices = [configured] if configured else sorted(glob.glob("/dev/serial/by-id/usb-u-blox*"))
    if len(devices) != 1:
        raise OSError("select exactly one USB GPS")
    fd = os.open(devices[0], os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        old = termios.tcgetattr(fd)
        termios.tcsetattr(fd, termios.TCSANOW, [0,0,termios.CS8|termios.CREAD|termios.CLOCAL,0,termios.B9600,termios.B9600,old[6][:]])
        buf = b""
        LOG.info("USB GPS opened")
        while True:
            if not select.select([fd], [], [], 10)[0]:
                raise OSError("USB GPS stopped sending")
            data = os.read(fd, 4096)
            if not data:
                raise OSError("USB GPS disconnected")
            *lines, buf = (buf + data).split(b"\n")
            buf = buf[-4096:]
            for line in lines:
                fix = position(line)
                if fix and abs(time.time() - fix["tst"]) <= 15:
                    yield fix
    finally:
        os.close(fd)


def post(path, payload):
    api = os.environ["KISERO_API_URL"].rstrip("/")
    request = Request(api + path, json.dumps(payload, allow_nan=False).encode(), {
        "Authorization": "Bearer " + os.environ["KISERO_DEVICE_TOKEN"], "Content-Type": "application/json"})
    with urlopen(request, timeout=12) as response:
        return json.load(response)


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    path = Path(os.getenv("KISERO_BOAT_DB", "/var/lib/kisero/boat.sqlite3"))
    db = connect(path)
    tracker = Movement(db)
    latest = None

    def send():
        last = None
        while True:
            payload = latest
            if payload and payload["tst"] != last and time.time() - payload["tst"] <= 15:
                try:
                    if post("/v1/alarm/boat", payload).get("accepted"):
                        last = payload["tst"]
                except Exception as error:
                    LOG.warning("Boat status not delivered (%s)", type(error).__name__)
            time.sleep(15)

    threading.Thread(target=send, daemon=True).start()
    while True:
        try:
            for fix in serial_fixes():
                tracker.observe(fix)
                latest = {**fix, "state": tracker.state}
        except (OSError, ValueError) as error:
            LOG.warning("USB GPS unavailable (%s)", type(error).__name__)
            time.sleep(10)


if __name__ == "__main__":
    main()
