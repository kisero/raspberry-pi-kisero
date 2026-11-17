import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "aws" / "function"))
from home_snapshot import merge_snapshot


class HomeSnapshotTest(unittest.TestCase):
    def test_an_unavailable_source_keeps_the_last_known_values(self):
        before = {"position": {"state": "moored", "location": "Puerto Banús", "observedAt": 100}}
        self.assertEqual(merge_snapshot(before, {"position": {"state": "unknown"}}), before)

    def test_late_records_cannot_replace_recent_readings(self):
        before = {"device": {"receivedAt": "2026-11-17T20:25:30Z", "armed": True}}
        earlier = {"device": {"receivedAt": "2026-11-17T20:25:00Z", "armed": False}}
        self.assertEqual(merge_snapshot(before, earlier), before)

    def test_snapshot_exposes_only_public_boat_position_fields(self):
        result = merge_snapshot({}, {"position": {
            "state": "sailing", "location": "Puerto Banús", "observedAt": 100,
            "lat": 36.5, "lon": -5, "phone": {"lat": 36.6, "lon": -5}}})
        self.assertEqual(result["position"], {
            "state": "sailing", "location": "Puerto Banús", "observedAt": 100})
