#!/usr/bin/env python3
"""
Load BirdNET CSV result files into the consolidated SQLite database.

Usage example:
    .venv/bin/python ingest_csv.py --db birdnet.sqlite res/res-*.txt
"""

from __future__ import annotations

import argparse
import csv
import logging
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Sequence

from dateutil import tz


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS stations (
  station_id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recordings (
  recording_id INTEGER PRIMARY KEY,
  station_id TEXT NOT NULL REFERENCES stations(station_id),
  file_basename TEXT NOT NULL UNIQUE,
  ts_start_utc INTEGER NOT NULL,
  duration_s REAL NOT NULL,
  qweek INTEGER NOT NULL,
  channel_count INTEGER NOT NULL DEFAULT 1,
  archived_at INTEGER
);

CREATE TABLE IF NOT EXISTS species (
  species_id INTEGER PRIMARY KEY,
  sci_name TEXT NOT NULL UNIQUE,
  common_name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS detections (
  detection_id INTEGER PRIMARY KEY,
  recording_id INTEGER NOT NULL REFERENCES recordings(recording_id) ON DELETE CASCADE,
  ts_utc INTEGER NOT NULL,
  offset_start_s REAL NOT NULL,
  dur_s REAL NOT NULL,
  confidence REAL NOT NULL,
  species_id INTEGER NOT NULL REFERENCES species(species_id),
  model_version TEXT NOT NULL,
  clip_hint TEXT,
  notes TEXT,
  UNIQUE (recording_id, offset_start_s, species_id, model_version)
);
"""

DEFAULT_DB = "birdnet.sqlite"
DEFAULT_TIMEZONE = "Europe/Helsinki"
DEFAULT_RAW_DIR = "raw"
MODEL_FALLBACK = "pre-2.3"
TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"


@dataclass(frozen=True)
class ModelVersion:
    version: str
    activated_at: int  # epoch seconds UTC


def iter_input_files(patterns: Sequence[str]) -> Iterator[Path]:
    seen: set[Path] = set()
    for pattern in patterns:
        p = Path(pattern)
        matches: Iterable[Path]
        if p.is_dir():
            matches = sorted(p.glob("*.txt"))
        else:
            matches = sorted(Path.cwd().glob(pattern))
            if not matches and "*" not in pattern and "?" not in pattern and "[" not in pattern:
                # Direct file path
                matches = [p] if p.exists() else []
        for match in matches:
            match = match.resolve()
            if match.suffix.lower() != ".txt":
                continue
            if match not in seen:
                seen.add(match)
                yield match


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create tables (no-op if already present) and enable WAL."""
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.executescript(SCHEMA_SQL)


def load_model_versions(path: Path) -> list[ModelVersion]:
    timeline: list[ModelVersion] = []
    if not path.exists():
        logging.warning("model-update-times.txt not found at %s; falling back to %s", path, MODEL_FALLBACK)
        return timeline

    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 2:
            logging.warning("Skipping malformed model version line: %s", line)
            continue
        version, iso_ts = parts
        try:
            dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        except ValueError as exc:
            logging.warning("Could not parse timestamp %s (%s): %s", iso_ts, version, exc)
            continue
        if dt.tzinfo is None:
            logging.warning("Timestamp %s missing timezone info; treating as UTC", iso_ts)
            dt = dt.replace(tzinfo=timezone.utc)
        timeline.append(ModelVersion(version=version, activated_at=int(dt.timestamp())))

    timeline.sort(key=lambda mv: mv.activated_at)
    return timeline


def resolve_model_version(timeline: Sequence[ModelVersion], ts_utc: int) -> str:
    for mv in reversed(timeline):
        if ts_utc >= mv.activated_at:
            return mv.version
    return MODEL_FALLBACK


def parse_station_and_stamp(path: Path) -> tuple[str, str]:
    stem = path.stem  # e.g., res-mokki-20230726_115804
    if stem.startswith("res-"):
        stem = stem[4:]
    parts = stem.split("-", 1)
    if len(parts) != 2:
        raise ValueError(f"Cannot parse station/timestamp from {path.name}")
    station, stamp = parts
    if len(station) == 0:
        raise ValueError(f"Empty station code in {path.name}")
    datetime.strptime(stamp, TIMESTAMP_FORMAT)  # validate
    return station, stamp


def make_timezone(name: str):
    tzinfo = tz.gettz(name)
    if tzinfo is None:
        raise ValueError(f"Unknown timezone '{name}'")
    return tzinfo


def parse_utc_timestamp(stamp: str) -> datetime:
    """Parse the UTC timestamp encoded in BirdNET result filenames."""
    naive = datetime.strptime(stamp, TIMESTAMP_FORMAT)
    return naive.replace(tzinfo=timezone.utc)


def compute_qweek(local_dt: datetime) -> int:
    return (local_dt.month - 1) * 4 + (local_dt.day - 1) // 7


def ensure_station(conn: sqlite3.Connection, station_id: str, display_name: str | None = None) -> None:
    display = display_name or station_id
    conn.execute(
        "INSERT INTO stations (station_id, display_name) VALUES (?, ?) "
        "ON CONFLICT(station_id) DO UPDATE SET display_name = excluded.display_name",
        (station_id, display),
    )


def ensure_recording(
    conn: sqlite3.Connection,
    station_id: str,
    file_basename: str,
    ts_start_utc: int,
    duration_s: float,
    qweek: int,
    channel_count: int = 1,
) -> int:
    conn.execute(
        """
        INSERT INTO recordings (station_id, file_basename, ts_start_utc, duration_s, qweek, channel_count)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(file_basename) DO UPDATE SET
            station_id = excluded.station_id,
            ts_start_utc = excluded.ts_start_utc,
            duration_s = excluded.duration_s,
            qweek = excluded.qweek,
            channel_count = excluded.channel_count
        """,
        (station_id, file_basename, ts_start_utc, duration_s, qweek, channel_count),
    )
    row = conn.execute(
        "SELECT recording_id FROM recordings WHERE file_basename = ?",
        (file_basename,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Unexpected: recording not found after insert ({file_basename})")
    return int(row[0])


def ensure_species(conn: sqlite3.Connection, sci_name: str, common_name: str, cache: dict[str, int]) -> int:
    if sci_name in cache:
        return cache[sci_name]
    conn.execute(
        """
        INSERT INTO species (sci_name, common_name) VALUES (?, ?)
        ON CONFLICT(sci_name) DO UPDATE SET common_name = excluded.common_name
        """,
        (sci_name, common_name),
    )
    row = conn.execute(
        "SELECT species_id FROM species WHERE sci_name = ?",
        (sci_name,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Species insert/select failed for {sci_name}")
    species_id = int(row[0])
    cache[sci_name] = species_id
    return species_id


def get_flac_duration(path: Path) -> float | None:
    if not path.exists():
        return None
    try:
        result = subprocess.run(
            ["soxi", "-D", str(path)],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("soxi not found; install sox to read FLAC durations") from exc
    except subprocess.CalledProcessError:
        logging.warning("Failed to read duration via soxi for %s", path)
        return None
    try:
        return float(result.stdout.strip())
    except ValueError:
        logging.warning("Invalid duration output from soxi for %s: %s", path, result.stdout.strip())
        return None


def read_csv_rows(path: Path) -> Iterator[dict[str, str]]:
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            yield row


def ingest_file(
    conn: sqlite3.Connection,
    path: Path,
    *,
    station_override: str | None,
    tzinfo,
    raw_dir: Path,
    model_timeline: Sequence[ModelVersion],
    default_duration: float | None,
) -> tuple[int, int]:
    station, stamp = parse_station_and_stamp(path)
    if station_override:
        station = station_override
    utc_dt = parse_utc_timestamp(stamp)
    local_dt = utc_dt.astimezone(tzinfo)
    ts_start_utc = int(utc_dt.timestamp())
    qweek = compute_qweek(local_dt)
    raw_path = raw_dir / f"{station}-{stamp}.flac"

    max_end = 0.0
    detections_to_write = []
    species_cache: dict[str, int] = {}

    for row in read_csv_rows(path):
        try:
            offset_start = float(row["Start (s)"])
            offset_end = float(row["End (s)"])
            confidence = float(row["Confidence"])
        except (KeyError, ValueError) as exc:
            logging.debug("Skipping row in %s due to parse error: %s", path.name, exc)
            continue
        sci_name = row.get("Scientific name", "").strip()
        common_name = row.get("Common name", "").strip()
        if not sci_name:
            logging.debug("Skipping row without scientific name in %s", path.name)
            continue
        max_end = max(max_end, offset_end)
        detections_to_write.append(
            (offset_start, offset_end - offset_start, confidence, sci_name, common_name)
        )

    if not detections_to_write:
        logging.info("No detections in %s", path.name)

    duration_s = get_flac_duration(raw_path)
    if duration_s is None:
        if default_duration is not None:
            duration_s = default_duration
            logging.info("Using fallback duration %.1f for %s (raw audio missing)", duration_s, raw_path.name)
        elif max_end:
            duration_s = max_end
            logging.info("Derived duration %.1f from CSV for %s", duration_s, path.name)
        else:
            raise RuntimeError(
                f"Could not determine duration for {path.name}; raw file {raw_path} missing and CSV empty"
            )

    ensure_station(conn, station)
    recording_id = ensure_recording(
        conn,
        station,
        path.name,
        ts_start_utc,
        duration_s,
        qweek,
        channel_count=1,
    )

    model_version = resolve_model_version(model_timeline, ts_start_utc)
    inserted = 0
    skipped = 0
    for offset_start, dur_s, confidence, sci_name, common_name in detections_to_write:
        if dur_s < 0:
            logging.debug(
                "Skipping detection with negative duration (%s) in %s",
                dur_s,
                path.name,
            )
            continue
        species_id = ensure_species(conn, sci_name, common_name, species_cache)
        ts_utc = ts_start_utc + offset_start
        cursor = conn.execute(
            """
            INSERT INTO detections (
                recording_id, ts_utc, offset_start_s, dur_s, confidence, species_id, model_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(recording_id, offset_start_s, species_id, model_version) DO UPDATE SET
                confidence = excluded.confidence,
                dur_s = excluded.dur_s
            """,
            (recording_id, ts_utc, offset_start, dur_s, confidence, species_id, model_version),
        )
        if cursor.rowcount == 1:
            inserted += 1
        else:
            skipped += 1

    logging.info(
        "Processed %s: station=%s detections=%d inserted=%d updated=%d duration=%.1fs model=%s",
        path.name,
        station,
        len(detections_to_write),
        inserted,
        skipped,
        duration_s,
        model_version,
    )
    return inserted, skipped


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest BirdNET CSV outputs into SQLite.")
    parser.add_argument("inputs", nargs="+", help="CSV files, directories, or glob patterns to ingest.")
    parser.add_argument("--db", default=DEFAULT_DB, help=f"SQLite database path (default: {DEFAULT_DB}).")
    parser.add_argument("--station", help="Override station code for all files (default: inferred from filename).")
    parser.add_argument(
        "--tz",
        default=DEFAULT_TIMEZONE,
        help=f"Timezone name for file timestamps (default: {DEFAULT_TIMEZONE}).",
    )
    parser.add_argument(
        "--raw-dir",
        default=DEFAULT_RAW_DIR,
        help=f"Directory that holds raw FLAC files (default: {DEFAULT_RAW_DIR}).",
    )
    parser.add_argument(
        "--default-duration",
        type=float,
        help="Fallback duration (seconds) if raw FLAC is missing and CSV cannot infer length.",
    )
    parser.add_argument(
        "--model-times",
        default="model-update-times.txt",
        help="Path to model-update-times.txt (default: model-update-times.txt).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level (DEBUG, INFO, WARNING, ...).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), format="%(message)s")

    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)

    try:
        ensure_schema(conn)
        tzinfo = make_timezone(args.tz)
        model_timeline = load_model_versions(Path(args.model_times))

        total_inserted = 0
        total_updated = 0
        processed = 0

        for path in iter_input_files(args.inputs):
            try:
                inserted, updated = ingest_file(
                    conn,
                    path,
                    station_override=args.station,
                    tzinfo=tzinfo,
                    raw_dir=Path(args.raw_dir),
                    model_timeline=model_timeline,
                    default_duration=args.default_duration,
                )
            except ValueError as exc:
                logging.warning("Skipping %s: %s", path.name, exc)
                continue
            except Exception as exc:
                logging.error("Failed to ingest %s: %s", path.name, exc)
                raise
            else:
                processed += 1
                total_inserted += inserted
                total_updated += updated
                conn.commit()

        logging.info(
            "Ingestion complete: files=%d inserted=%d updated=%d",
            processed,
            total_inserted,
            total_updated,
        )

    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
