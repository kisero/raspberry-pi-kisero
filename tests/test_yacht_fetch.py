import base64
import os
import tempfile
import struct
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import yacht_fetch


class MemoryExportTest(unittest.TestCase):
    def test_decodes_sailing_yacht_record(self):
        record = bytearray(b"\xff" * 64)
        struct.pack_into("<Iii7HhH", record, 0, 60, 364800000, -49500000, 0, 100,
                         0, 200, 0, 300, 0, 0, 123)
        record[31] = 6 << 5 | 7 << 2
        memory = b"<html><div id='D'>" + base64.b64encode(record) + b"</div></html>"
        points = yacht_fetch.parse_memory(memory)
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["_time"], datetime(2015, 1, 1, 0, 1))
        self.assertEqual(points[0]["_longitude"], -4.95)
        self.assertAlmostEqual(points[0]["_sog"], 1.94384449)
        self.assertAlmostEqual(float(points[0]["TWS"]), 5.83153348)

    def test_merges_missing_records_across_memory_downloads(self):
        start = datetime(2026, 9, 29)
        first = {"_time": start, "Memory Record": "first"}
        middle = {"_time": start + timedelta(seconds=15), "Memory Record": "middle"}
        last = {"_time": start + timedelta(seconds=30), "Memory Record": "last"}
        self.assertEqual(yacht_fetch.merge_memory([first, last], [middle, last]),
                         [first, middle, last])

    def test_partial_snapshot_salvages_only_complete_blocks(self):
        record = bytearray(32)
        record[31] = 7 << 5 | 7 << 2
        block = base64.b64encode(record)
        html = b"<html><div id='D'>" + block + b"\npartial"
        with self.assertLogs("kisero-yacht", level="WARNING"):
            decoded = yacht_fetch.parse_memory(html, allow_partial=True)
        self.assertEqual([point["Memory Record"] for point in decoded], [block.decode()])

    def test_truncated_memory_is_rejected(self):
        with self.assertRaises(ValueError):
            yacht_fetch.parse_memory(b"<html><div id='D'>aGVsbG8=")


class VoyageTest(unittest.TestCase):
    def test_stationary_interval_splits_outings_and_short_movement_is_skipped(self):
        start = datetime(2026, 10, 1)
        def run(begin, end, speed):
            return [{"_time": start + timedelta(seconds=t), "_sog": speed}
                    for t in range(begin, end + 1, 15)]
        points = run(0, 600, 4) + run(615, 1215, 0.3) + run(1230, 1845, 3)
        points += run(2500, 2530, 2)
        outings = yacht_fetch.historical_outings(points)
        self.assertEqual([(g[0]["_time"], g[-1]["_time"]) for g in outings],
                         [(start, start + timedelta(seconds=615)),
                          (start + timedelta(seconds=1230), start + timedelta(seconds=1845))])

    def test_live_gps_stop_allows_last_reading_before_boat_stops(self):
        start = datetime(2026, 10, 1)
        points = [{"_time": start + timedelta(seconds=t), "_sog": 4}
                  for t in range(0, 616, 15)]
        epoch = yacht_fetch.seconds(start)
        self.assertEqual(yacht_fetch.select_outing(points, epoch, epoch + 700, 15), points)
        with self.assertRaises(ValueError):
            yacht_fetch.select_outing(points, epoch, epoch + 1000, 15)


class CollectorTest(unittest.TestCase):
    def test_queues_local_export_during_internet_outage(self):
        start = datetime(2026, 9, 1)
        points = [{"_time": start + timedelta(seconds=t), "_latitude": 36.48,
                   "_longitude": -4.95, "_sog": 4, "Memory Record": "fixture"}
                  for t in range(0, 601, 15)]
        epoch = yacht_fetch.seconds(start)
        with tempfile.TemporaryDirectory() as folder:
            db_path = str(Path(folder) / "voyages.sqlite3")
            db = yacht_fetch.connect(db_path)
            with db:
                db.execute("INSERT INTO trips(started,ended) VALUES (?,?)", (epoch, epoch + 600))
            with (patch.dict(os.environ, {"KISERO_BOAT_DB": db_path}),
                  patch.object(yacht_fetch, "published_windows", side_effect=OSError("offline")),
                  patch.object(yacht_fetch, "download", return_value=b"</div></html>"),
                  patch.object(yacht_fetch, "parse_memory", return_value=points)):
                with self.assertLogs("kisero-yacht", level="WARNING"):
                    yacht_fetch.collect("http://10.42.0.149:1458/", 15)
            raw, sent = db.execute("SELECT csv,sent FROM trips").fetchone()
            self.assertEqual(raw, yacht_fetch.csv_bytes(points))
            self.assertEqual(sent, 0)
            db.close()


if __name__ == "__main__":
    unittest.main()
