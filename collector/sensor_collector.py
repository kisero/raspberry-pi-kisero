#!/usr/bin/env python3
"""Read an SHT3x sensor, durably queue it, and upload pending samples."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from smbus2 import SMBus, i2c_msg

API_URL = os.environ.get("KISERO_API_URL", "").rstrip("/")
DEVICE_TOKEN = os.environ.get("KISERO_DEVICE_TOKEN", "")
QUEUE_PATH = Path(os.environ.get("KISERO_SENSOR_QUEUE", "/var/lib/kisero/sensors.sqlite3"))
I2C_BUS = int(os.environ.get("KISERO_I2C_BUS", "1"))
SENSOR_ADDRESSES = (0x44, 0x45)


def crc8(data: list[int]) -> int:
    crc = 0xFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x31) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def read_sensor() -> tuple[int, float, float]:
    """Return (I2C address, Celsius, relative humidity) with CRC validation."""
    errors = []
    for address in SENSOR_ADDRESSES:
        try:
            with SMBus(I2C_BUS) as bus:
                bus.i2c_rdwr(i2c_msg.write(address, [0x24, 0x00]))
                time.sleep(0.02)
                message = i2c_msg.read(address, 6)
                bus.i2c_rdwr(message)
                raw = list(message)
            if crc8(raw[0:2]) != raw[2] or crc8(raw[3:5]) != raw[5]:
                raise ValueError("SHT3x response failed CRC validation")
            raw_temperature = (raw[0] << 8) | raw[1]
            raw_humidity = (raw[3] << 8) | raw[4]
            temperature_c = -45.0 + 175.0 * raw_temperature / 65535.0
            humidity_pct = 100.0 * raw_humidity / 65535.0
            if not (-40.0 <= temperature_c <= 125.0 and 0.0 <= humidity_pct <= 100.0):
                raise ValueError("SHT3x returned an out-of-range measurement")
            return address, temperature_c, humidity_pct
        except (OSError, ValueError) as error:
            errors.append(f"0x{address:02x}: {error}")
    raise RuntimeError("No SHT3x responded on I2C bus %d (%s)" % (I2C_BUS, "; ".join(errors)))


def connect_queue() -> sqlite3.Connection:
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = sqlite3.connect(QUEUE_PATH, timeout=10)
    os.chmod(QUEUE_PATH, 0o600)
    db.execute("""CREATE TABLE IF NOT EXISTS samples (
        observed_at TEXT PRIMARY KEY,
        payload TEXT NOT NULL
    )""")
    db.commit()
    return db


def queue_sample(sample: dict) -> None:
    with connect_queue() as db:
        db.execute("INSERT OR IGNORE INTO samples(observed_at, payload) VALUES (?, ?)",
                   (sample["observedAt"], json.dumps(sample, separators=(",", ":"))))


def upload_pending() -> None:
    if not API_URL or not DEVICE_TOKEN:
        raise RuntimeError("KISERO_API_URL and KISERO_DEVICE_TOKEN must be set in the device environment file")
    with connect_queue() as db:
        pending = db.execute("SELECT observed_at, payload FROM samples ORDER BY observed_at").fetchall()
    for observed_at, payload in pending:
        request = urllib.request.Request(
            API_URL + "/v1/sensors",
            data=payload.encode("utf-8"),
            headers={"Authorization": "Bearer " + DEVICE_TOKEN,
                     "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))
        if not result.get("accepted") or result.get("observedAt") != observed_at:
            raise RuntimeError("Sensor API did not acknowledge the queued sample")
        with connect_queue() as db:
            db.execute("DELETE FROM samples WHERE observed_at = ?", (observed_at,))
        print(json.dumps({"uploaded": observed_at}, separators=(",", ":")), flush=True)


def main() -> int:
    address, temperature_c, humidity_pct = read_sensor()
    sample = {
        "observedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "temperatureC": round(temperature_c, 2),
        "humidityPct": round(humidity_pct, 1),
    }
    if sys.argv[1:] == ["--check"]:
        print(json.dumps({"sensorAddress": f"0x{address:02x}", **sample}, separators=(",", ":")), flush=True)
        return 0
    if sys.argv[1:]:
        raise RuntimeError("usage: sensor_collector.py [--check]")
    queue_sample(sample)
    print(json.dumps({"sensorAddress": f"0x{address:02x}", **sample}, separators=(",", ":")), flush=True)
    upload_pending()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, urllib.error.URLError, json.JSONDecodeError) as error:
        print(f"sensor collection failed: {error}", file=sys.stderr, flush=True)
        raise SystemExit(1)
