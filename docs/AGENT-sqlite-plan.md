# SQLite Migration Plan

## Objectives
- Replace the CSV-only results workflow with a single SQLite database that preserves all information needed for review, clipping, and analytics.
- Align the schema with existing artifacts (`res/*`, `raw/*`, `obsloop.sh`) so we can import historical detections and keep the recording loop running unchanged while we transition.
- Stage the work to minimise downtime: build the database, backfill old observations, teach the pipeline to dual-write, then migrate the tooling.

## Schema Overview

### Design Notes
- Each BirdNET CSV row carries both the absolute recording start (encoded in the filename) and the offset within that recording. We will persist both: `ts_utc` (absolute detection start in epoch seconds) and `offset_start_s` (relative to the recording), plus `dur_s`. This keeps clip generation straightforward and avoids recomputing offsets repeatedly.
- A `recordings` table captures per-file metadata (station, start time, Q-week, path hints). Observations reference recordings via foreign key, so we can track archival state without duplicating filenames in every detection row.
- `model_version` lives on the observation; it is looked up during import via `model-update-times.txt`. If later we change filters or pipeline parameters, we can extend the schema with a `pipeline_version` column without disturbing the core tables.

### SQL Definition
```sql
PRAGMA foreign_keys = ON;

CREATE TABLE stations (
  station_id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL
);

CREATE TABLE recordings (
  recording_id INTEGER PRIMARY KEY,
  station_id TEXT NOT NULL REFERENCES stations(station_id),
  file_basename TEXT NOT NULL UNIQUE,        -- e.g. res-mokki-20240601_030000.txt
  ts_start_utc INTEGER NOT NULL,             -- epoch seconds, hour-aligned
  duration_s REAL NOT NULL,
  qweek INTEGER NOT NULL,                    -- custom 48-week scheme from obsloop.sh
  channel_count INTEGER NOT NULL DEFAULT 1,
  archived_at INTEGER                        -- epoch seconds when raw audio moved off-device
);

CREATE TABLE species (
  species_id INTEGER PRIMARY KEY,
  sci_name TEXT NOT NULL UNIQUE,
  common_name TEXT NOT NULL
);

CREATE TABLE detections (
  detection_id INTEGER PRIMARY KEY,
  recording_id INTEGER NOT NULL REFERENCES recordings(recording_id) ON DELETE CASCADE,
  ts_utc INTEGER NOT NULL,                   -- absolute detection start (epoch seconds)
  offset_start_s REAL NOT NULL,              -- Start (s) from BirdNET CSV
  dur_s REAL NOT NULL,                       -- End - Start from CSV
  confidence REAL NOT NULL,
  species_id INTEGER NOT NULL REFERENCES species(species_id),
  model_version TEXT NOT NULL,
  clip_hint TEXT,                            -- optional: existing clip file, if any
  notes TEXT,
  UNIQUE (recording_id, offset_start_s, species_id, model_version) ON CONFLICT IGNORE
);
```

### Index Strategy
- `CREATE INDEX detections_ts_idx ON detections(ts_utc);` – fast chronologically bounded queries.
- `CREATE INDEX detections_species_idx ON detections(species_id, ts_utc DESC);` – supports species lookups and recent history.
- `CREATE INDEX detections_confidence_idx ON detections(confidence DESC);` – optional, for high-confidence filtering; monitor before adding.
- `CREATE INDEX recordings_station_time_idx ON recordings(station_id, ts_start_utc DESC);` – latest recordings per station.
- No standalone index on `station_id` inside `detections`; the foreign key plus composite indexes cover the expected queries.

## Migration Phases

### Phase 1 – Database Creation
- Generate the SQLite schema (SQL above) and seed the `stations` table (initially `mokki`).
- Capture the schema in version control (SQL file and migration notes) and document how to initialise the DB on-device.

### Phase 2 – Historical Backfill
- Write an ingestion script (`.venv/bin/python ingest_csv.py …`) that scans existing `res/*.txt` files, parses BirdNET columns, computes `ts_utc = recording.ts_start_utc + Start (s)`, and loads rows into the new tables.
- During import identify or create the corresponding `recordings` row using the file basename, populate `duration_s` (60 or 3600 depending on loop config), and derive `qweek` using the current shell logic (reuse the 48-week helper from `obsloop.sh` so the numbers stay aligned).
- Map species names to IDs; seed new species as they appear. Maintain a CSV→species table lookup cache to keep ingestion idempotent.
- Backfill `model_version` by reading `model-update-times.txt` and selecting the version active at `ts_start_utc`.
- Validate parity: compare counts per species/day between CSV and DB outputs for a few sample periods.

### Phase 3 – Pipeline Dual-Write
- Extend `obsloop.sh` (or a helper the service calls) to run the ingestion script immediately after each analyzer run. Keep CSV emission untouched for now.
- Ensure the ingestion step is idempotent: if a restart reprocesses the latest file, the `UNIQUE` constraint prevents duplicates.
- Add lightweight health logging (e.g., append to syslog or a daily summary file) so we notice ingestion failures quickly.

### Phase 4 – Tooling Update
- Teach `species.py` to read from SQLite when available: swap Polars CSV reads for SQL queries while keeping command-line switches (`--species`, `--counts`, `--clip`) behaving identically.
- For regex searches, perform filtering in Python using compiled regex over the result set; document the change in CLI help.
- Update clip generation to use `detections.offset_start_s` and `recordings.ts_start_utc` to compute the same nicenames as today.
- Once parity is proven, optionally add maintenance utilities (e.g., vacuum, stats export) and consider retiring bulk CSV reads.

## Operational Notes
- Backups: include the SQLite file in the same rsync routine as `raw/` archives. Perform `VACUUM` after large backfills to keep file size controlled.
- Future schema changes (e.g., storing background noise metrics) should follow a migration script pattern to keep the device in sync.
- Keep the CSV pipeline for at least one full migration cycle so you can fall back if the database encounters corruption; phase-out can happen after several weeks of successful dual writes.

## Open Follow-ups
- Build a small regression checklist (counts over the last 24h, first/last detection timestamps, clip playback) to run after each phase.
- Decide when to enforce foreign key checks during ingestion (`PRAGMA defer_foreign_keys = ON`) depending on batch size and performance on the Pi.
- Evaluate whether to store additional recording metadata (gain, sample rate) once we touch `obsloop.sh`; the schema leaves room for new columns without breaking ingestion.
