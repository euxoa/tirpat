#!/usr/bin/env python3
"""
Correct recording and detection timestamps that were ingested with a local-time offset.

Early versions of ingest_csv.py interpreted BirdNET result basenames as local time even
though obsloop.sh stamps them in UTC. This script reparses the basename, derives the
intended UTC timestamp, and adjusts both recordings.ts_start_utc and detections.ts_utc.
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from dateutil import tz

from ingest_csv import compute_qweek, make_timezone, parse_station_and_stamp, parse_utc_timestamp


def iter_recordings(conn: sqlite3.Connection):
    cur = conn.execute("SELECT recording_id, file_basename, ts_start_utc, qweek FROM recordings")
    try:
        yield from cur
    finally:
        cur.close()


def adjust_timestamps(db_path: Path, tz_name: str, dry_run: bool = False) -> tuple[int, int]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    tzinfo = make_timezone(tz_name)

    recordings_updated = 0
    detections_updated = 0

    try:
        for row in iter_recordings(conn):
            rec_id = row["recording_id"]
            basename = row["file_basename"]
            station, stamp = parse_station_and_stamp(Path(basename))

            utc_dt = parse_utc_timestamp(stamp)
            correct_ts = int(utc_dt.timestamp())
            delta = correct_ts - row["ts_start_utc"]
            local_dt = utc_dt.astimezone(tzinfo)
            correct_qweek = compute_qweek(local_dt)

            if delta == 0 and correct_qweek == row["qweek"]:
                continue

            recordings_updated += 1

            if not dry_run:
                conn.execute(
                    "UPDATE recordings SET ts_start_utc = ?, qweek = ? WHERE recording_id = ?",
                    (correct_ts, correct_qweek, rec_id),
                )

            if delta != 0:
                detections_updated += conn.execute(
                    "SELECT COUNT(*) FROM detections WHERE recording_id = ?", (rec_id,)
                ).fetchone()[0]
                if not dry_run:
                    conn.execute(
                        "UPDATE detections SET ts_utc = ts_utc + ? WHERE recording_id = ?",
                        (delta, rec_id),
                    )

        if not dry_run:
            conn.commit()
    finally:
        conn.close()

    return recordings_updated, detections_updated


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("birdnet.sqlite"), help="SQLite database file")
    parser.add_argument(
        "--timezone",
        default="Europe/Helsinki",
        help="Local timezone for qweek recomputation (default: Europe/Helsinki)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show planned changes without mutating the database")

    args = parser.parse_args()
    recordings, detections = adjust_timestamps(args.db, args.timezone, dry_run=args.dry_run)

    label = "would update" if args.dry_run else "updated"
    print(f"{label} {recordings} recordings and {detections} detections in {args.db}")


if __name__ == "__main__":
    main()
