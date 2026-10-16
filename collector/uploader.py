#!/usr/bin/env python3
"""Explicitly upload one Yacht Devices CSV export to the Kisero API."""
import base64
import json
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

from pipeline import build
from durable_queue import acknowledge, enqueue, pending


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: python3 collector/uploader.py export.csv")
    api = os.environ.get("KISERO_API_URL", "").rstrip("/")
    token = os.environ.get("KISERO_DEVICE_TOKEN", "")
    if not api or not token:
        raise SystemExit("Set KISERO_API_URL and KISERO_DEVICE_TOKEN in the runtime environment.")
    source = Path(sys.argv[1])
    queue_path = Path(os.environ.get("KISERO_QUEUE_PATH", "var/collector.db"))
    enqueue(queue_path, source.read_bytes())
    for digest, csv_bytes in pending(queue_path):
        with tempfile.TemporaryDirectory(prefix="kisero-derived-") as work:
            derived = Path(work)
            staged_csv = derived / "source.csv"
            staged_csv.write_bytes(csv_bytes)
            index = build(staged_csv, derived / "tracks")
            trips = [json.loads(path.read_text()) for path in sorted((derived / "tracks").glob("*.json")) if path.name != "index.json"]
            payload = json.dumps({"rawCsvBase64": base64.b64encode(csv_bytes).decode("ascii"),
                                  "index": index, "trips": trips}).encode()
            request = urllib.request.Request(api + "/v1/ingest", data=payload,
                headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(request, timeout=30) as response:
                result = json.loads(response.read().decode())
            if result.get("accepted") and result.get("sha256") == digest:
                acknowledge(queue_path, digest)
            print(json.dumps(result))


if __name__ == "__main__":
    main()
