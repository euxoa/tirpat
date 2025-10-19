# SQLite Migration Notes

## Snapshot Of Current Workflow
- BirdNET analyzer drops CSV result files in `res/` with per-detection columns: start/end offsets (s), scientific/common names, confidence.
- Typical inspection commands (from `~/.bash_history`):  
  - `.venv/bin/python species.py $(ls res/* | tail -24)  -p .80 --counts`  
  - `.venv/bin/python species.py $(ls res/* | tail -3000)  -p .90 --raw --species harmaahaikara | less`  
  These rely on quick glob/tail selection of recent files, filtering by species regex, adjusting confidence thresholds, and occasionally piping to `less`.
- `species.py` uses Polars→Pandas to lazily read the selected CSVs, deduplicate detections, format relative/absolute times, and optionally produce clips.

## Review Of Proposed Schema
```sql
CREATE TABLE species (
  species_id INTEGER PRIMARY KEY,
  sci_name TEXT NOT NULL UNIQUE,
  common_name TEXT NOT NULL
);

CREATE TABLE detections (
  id INTEGER PRIMARY KEY,
  station_id TEXT NOT NULL,
  ts_utc INTEGER NOT NULL,      -- epoch seconds
  dur_s REAL NOT NULL,
  species_id INTEGER NOT NULL REFERENCES species(species_id),
  confidence REAL NOT NULL,
  file_hint TEXT,
  model_version TEXT,
  UNIQUE (station_id, ts_utc, dur_s, species_id, file_hint) ON CONFLICT IGNORE
);
```

- **Missing offsets:** CSV rows carry `Start (s)` / `End (s)`. Storing only `dur_s` loses the offset that makes each detection unique and reconstructable. Suggest keeping at least `offset_start_s` (float) and optionally `offset_end_s` or `offset_center_s`, so we can reverse-engineer clip centers, deduplicate correctly, and export clips later. These offsets originate from the analyzer output driven by `obsloop.sh`, so keep their original semantics intact.
- **Meaning of `ts_utc`:** `obsloop.sh` timestamps each filename with the UTC start of the hour-long recording. Use that as `file_start_utc`, and compute detection timestamps as `file_start_utc + offset_start_s`. If you store the absolute detection start in `ts_utc`, keep the offset columns as well for clip generation and integrity checks.
- **File-level metadata:** Consider a `recordings` table (`station_id`, `file_start_utc`, `file_path`, `qweek`, `duration_s`). That keeps `detections` lean and lets you track when raw audio files are archived or pruned.
- **Station ID cardinality:** If you keep one station (`mokki`), an index on `station_id` adds little. A partial composite index on `(station_id, ts_utc)` remains useful if you add other stations later.
- **Model version and pipeline:** Keeping `model_version` is helpful when updating BirdNET. `model-update-times.txt` lists changes: plan how to populate the column (e.g. lookup by timestamp during import). Add a `pipeline_version` or `analysis_hash` if you tweak filters or the analyzer parameters.

## Query Parity With Today’s Usage
- **Latest batches:** `SELECT * FROM detections WHERE station_id='mokki' ORDER BY ts_utc DESC LIMIT 24;`
- **Species regex analogue:** SQLite lacks native regex; you’d need `REGEXP` extension or filter in Python. If you rely on regex (`--species mustalintu`), plan for a user-defined function or a LIKE-based fallback.
- **Confidence threshold & counts:**  
  `SELECT species_id, COUNT(*) FROM detections WHERE confidence >= 0.80 AND ts_utc >= strftime('%s','now','-24 hours') GROUP BY species_id ORDER BY COUNT(*) DESC;`
- **Clip production:** Requires offsets. With `offset_start_s`, you can reconstruct `nicetime` and generate filenames the same way `species.py` does.

## Data Ingestion Considerations
- **Pipeline hook:** After each analyzer run, append detections into SQLite before (or instead of) writing CSV. Options:  
  1. Modify `obsloop.sh` to call a small Python script that parses the fresh CSV and inserts rows.  
  2. Replace CSV emission with direct DB insert in `analyze.py` (requires patching upstream).  
  3. Run a periodic “harvester” that watches `res/` for new files and imports them, then moves archived CSVs elsewhere.
- **Offsets during import:** During ingestion, read the CSV `Start (s)` / `End (s)` values and store them as `offset_start_s` / `offset_end_s`. Combine with the file basename (UTC hour from `obsloop.sh`) to reconstruct absolute detection timestamps.
- **Model version capture:** When ingesting, join each detection with the active analyzer model version using `model-update-times.txt` (e.g. pick the latest entry with timestamp ≤ file start) and populate `detections.model_version`.
- **Idempotency:** Keep `file_hint` (e.g., basename `res-mokki-YYYYmmdd_hhmmss.txt`) plus offsets in the unique constraint so re-imports don’t duplicate rows.
- **Archival sync:** When raw audio is moved off-device, update a `recordings.archived_at` column or maintain a sidecar table so you know which detections still have accessible audio.

## Tooling Impact
- `species.py` would need a new SQLite code path (or a separate CLI) to avoid reading thousands of CSVs. Polars can query SQLite via `read_database_uri`, or you can use DuckDB with `sqlite_scan`.
- Maintain the existing CSV workflow in parallel until the DB path is trusted—especially because on-device experimentation currently happens “in production.”
- Wrap common queries (`latest`, `counts`, `species search`) in a helper script so you don’t memorize SQL, mirroring today’s flags.

## Pros And Trade-offs
- **Pros:** Smaller on-device footprint than DuckDB; durable single-file database; simpler to rsync/backup; easy to expose via simple APIs; handles incremental updates well.
- **Cons:** Lacks built-in regex/window functions without extensions; ad-hoc analytics (e.g. percentile over long time spans) are faster in Polars/DuckDB. You may still prefer Polars for exploratory crunching—export slices from SQLite into Polars DataFrames.
- **Performance fit:** Raspberry Pi-class hardware handles SQLite inserts/queries comfortably at hourly cadence. Just ensure you index on the columns you filter by (`ts_utc`, `species_id`, `confidence`).

## Recommendation
SQLite is a solid upgrade for durable storage and quick retrieval, provided you amend the schema to retain detection offsets and either expose regex searches or accept LIKE-based filters. Plan the ingestion script and helper CLI first, test alongside existing `species.py` flows, then phase out bulk CSV reads once parity is proven. DuckDB/Polars remain valuable for heavy analysis, but SQLite as the authoritative store should work well for your operational workflow.
