import base64
import struct
import unittest
from datetime import datetime, timedelta

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


if __name__ == "__main__":
    unittest.main()
