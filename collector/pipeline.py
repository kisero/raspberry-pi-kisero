#!/usr/bin/env python3
"""Parse Yacht Devices CSV exports and derive configurable underway trips."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path


def parse_export(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = csv.DictReader(stream, delimiter=";")
        if not rows.fieldnames or "Time" not in rows.fieldnames:
            raise ValueError("CSV must contain a Time column")
        result = []
        for row in rows:
            point = {key.strip(): (value or "").strip() for key, value in row.items() if key}
            point["_time"] = datetime.strptime(point["Time"].strip('"'), "%d/%m/%Y, %H:%M:%S")
            for key in ("Latitude", "Longitude", "SOG"):
                point["_" + key.lower()] = float(point[key].replace(",", "."))
            result.append(point)
    result.sort(key=lambda p: p["_time"])
    return result


def distance_nm(a: dict, b: dict) -> float:
    lat1, lat2 = math.radians(a["_latitude"]), math.radians(b["_latitude"])
    dlat = lat2 - lat1
    dlon = math.radians(b["_longitude"] - a["_longitude"])
    hav = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 3440.065 * 2 * math.asin(min(1, math.sqrt(hav)))


def underway_trips(points: list[dict], speed_kn: float = 1.0, gap_minutes: int = 20,
                   minimum_minutes: int = 10) -> list[list[dict]]:
    moving = [p for p in points if p["_sog"] >= speed_kn]
    groups: list[list[dict]] = []
    for point in moving:
        if not groups or (point["_time"] - groups[-1][-1]["_time"]).total_seconds() > gap_minutes * 60:
            groups.append([point])
        else:
            groups[-1].append(point)
    return [g for g in groups if len(g) > 1 and
            (g[-1]["_time"] - g[0]["_time"]).total_seconds() >= minimum_minutes * 60]


def build(path: Path, output: Path, speed_kn: float = 1.0, gap_minutes: int = 20,
          minimum_minutes: int = 10) -> dict:
    points = parse_export(path)
    trips = underway_trips(points, speed_kn, gap_minutes, minimum_minutes)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    output.mkdir(parents=True, exist_ok=True)
    summaries = []
    for group in trips:
        trip_id = group[0]["_time"].strftime("%Y%m%dT%H%M%S")
        track = [[p["_longitude"], p["_latitude"], p["_time"].isoformat(timespec="seconds"), p["_sog"]]
                 for p in group]
        summary = {"id": trip_id, "start": track[0][2], "end": track[-1][2],
                   "pointCount": len(group), "distanceNm": round(sum(distance_nm(a, b) for a, b in zip(group, group[1:])), 2),
                   "averageSogKn": round(sum(p["_sog"] for p in group) / len(group), 1),
                   "maxSogKn": round(max(p["_sog"] for p in group), 1)}
        summaries.append(summary)
        (output / f"{trip_id}.json").write_text(json.dumps({**summary, "track": track}, indent=2) + "\n")
    index = {"schemaVersion": 1, "sourceSha256": digest, "pointCount": len(points), "trips": summaries}
    (output / "index.json").write_text(json.dumps(index, indent=2) + "\n")
    return index


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path, help="Yacht Devices CSV export")
    parser.add_argument("--output", type=Path, default=Path("var/derived"))
    parser.add_argument("--speed-kn", type=float, default=1.0)
    parser.add_argument("--gap-minutes", type=int, default=20)
    parser.add_argument("--minimum-minutes", type=int, default=10)
    args = parser.parse_args()
    print(json.dumps(build(args.csv, args.output, args.speed_kn, args.gap_minutes, args.minimum_minutes), indent=2))


if __name__ == "__main__":
    main()
