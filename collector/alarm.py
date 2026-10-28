#!/usr/bin/env python3
"""PIR alarm: local operation, durable event outbox, authenticated cloud control."""
import json
import logging
import os
import signal
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from gpiozero import DigitalInputDevice, DigitalOutputDevice
from gpiozero.pins.lgpio import LGPIOFactory

LOG = logging.getLogger("kisero-alarm")

def stamp(value=None):
    return datetime.fromtimestamp(value if value is not None else time.time(), timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

class Alarm:
    def __init__(self):
        path = Path(os.getenv("KISERO_ALARM_DB", "/var/lib/kisero/alarm.sqlite3"))
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        os.chmod(path, 0o600)
        self.db.executescript("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT); CREATE TABLE IF NOT EXISTS outbox (id TEXT PRIMARY KEY, body TEXT NOT NULL);")
        row = self.db.execute("SELECT value FROM settings WHERE key='control'").fetchone()
        saved = json.loads(row[0]) if row else {"armed": False, "version": 0}
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.dirty = threading.Event()
        self.armed = saved["armed"]
        self.version = saved["version"]
        self.motion = False
        self.ready = False
        self.sounding = False
        self.warmup = time.monotonic() + 60
        self.exit_at = time.monotonic() + 30 if self.armed else 0
        self.sound_until = 0
        self.api = os.environ["KISERO_API_URL"].rstrip("/")
        self.token = os.environ["KISERO_DEVICE_TOKEN"]

    def event(self, kind):
        with self.lock:
            row = {"id": uuid.uuid4().hex, "observedAt": stamp(), "kind": kind,
                   "motion": self.motion, "armed": self.armed}
            self.db.execute("INSERT INTO outbox VALUES (?,?)", (row["id"], json.dumps(row)))
            self.db.commit()
            self.dirty.set()
            LOG.info("%s: motion=%s armed=%s", kind, self.motion, self.armed)

    def apply(self, control):
        with self.lock:
            if not isinstance(control.get("armed"), bool) or not isinstance(control.get("version"), int):
                raise ValueError("invalid remote control")
            if control["version"] <= self.version:
                return
            changed = self.armed != control["armed"]
            self.armed, self.version = control["armed"], control["version"]
            self.db.execute("INSERT OR REPLACE INTO settings VALUES ('control',?)", (json.dumps(control),))
            self.db.commit()
            if changed:
                self.exit_at = time.monotonic() + 30 if self.armed else 0
                if not self.armed:
                    self.sound_until = 0
                self.event("armed" if self.armed else "disarmed")
            self.dirty.set()

    def request(self, path, body=None):
        headers = {"Authorization": "Bearer " + self.token}
        if body is not None:
            headers["Content-Type"] = "application/json"
        req = Request(self.api + path, data=json.dumps(body).encode() if body is not None else None, headers=headers)
        with urlopen(req, timeout=5) as response:
            return json.load(response)

    def snapshot(self):
        with self.lock:
            remaining = max(self.warmup, self.exit_at) - time.monotonic() if self.armed else 0
            return {"observedAt": stamp(), "armed": self.armed, "controlVersion": self.version,
                    "motion": self.motion, "sounding": self.sounding, "ready": self.ready,
                    "armingUntil": stamp(time.time() + remaining) if remaining > 0 else None}

    def network(self):
        next_control = next_status = retry = 0
        while not self.stop.is_set():
            try:
                if time.monotonic() >= next_control:
                    self.apply(self.request("/v1/alarm/device")["control"])
                    next_control = time.monotonic() + 3
                if self.dirty.is_set() or time.monotonic() >= next_status:
                    self.dirty.clear()
                    self.apply(self.request("/v1/alarm/device", self.snapshot())["control"])
                    next_status = time.monotonic() + 30
                with self.lock:
                    row = self.db.execute("SELECT id,body FROM outbox ORDER BY rowid LIMIT 1").fetchone()
                if row:
                    result = self.request("/v1/motion", json.loads(row[1]))
                    if result.get("id") != row[0] or not result.get("accepted"):
                        raise ValueError("upload was not acknowledged")
                    with self.lock:
                        self.db.execute("DELETE FROM outbox WHERE id=?", (row[0],))
                        self.db.commit()
                    continue
                retry = 0
                self.stop.wait(.2)
            except Exception as exc:
                retry += 1
                # Never include requests or credentials in logs.
                LOG.warning("Cloud unavailable (%s); retaining local control and queued events", type(exc).__name__)
                self.dirty.set()
                self.stop.wait(min(30, 2 * retry))

    def run(self):
        factory = LGPIOFactory(chip=0)
        pir = DigitalInputDevice(26, pull_up=False, pin_factory=factory)
        buzzer = DigitalOutputDevice(18, active_high=True, initial_value=False, pin_factory=factory)
        worker = threading.Thread(target=self.network, daemon=True)
        worker.start()
        candidate, since = bool(pir.value), time.monotonic()
        try:
            while not self.stop.wait(.05):
                tick = time.monotonic()
                current = bool(pir.value)
                if current != candidate:
                    candidate, since = current, tick
                with self.lock:
                    if not self.ready and tick >= self.warmup:
                        self.ready = True
                        self.motion = candidate
                        self.event("ready")
                    elif self.ready and candidate != self.motion and tick - since >= .2:
                        self.motion = candidate
                        self.event("motion")
                        if self.motion and self.armed and tick >= self.exit_at:
                            self.sound_until = tick + 10
                    # A high PIR at the end of an exit delay must also trigger.
                    if self.ready and self.armed and self.exit_at and tick >= self.exit_at:
                        self.exit_at = 0
                        if self.motion:
                            self.sound_until = tick + 10
                    sounding = self.ready and self.armed and tick < self.sound_until
                    if sounding != self.sounding:
                        self.sounding = sounding
                        self.event("triggered" if sounding else "silenced")
                    buzzer.value = sounding and (tick % .5 < .15)
        finally:
            buzzer.off()
            buzzer.close()
            pir.close()
            self.stop.set()
            worker.join(timeout=6)
            self.db.close()
            factory.close()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    alarm = Alarm()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: alarm.stop.set())
    alarm.run()
