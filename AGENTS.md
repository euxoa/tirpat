# AGENTS

## Purpose
- Personal BirdNET installation deployed at a summer cottage in Parikkala (61.46°N, 29.39°E); long-running bare-bones setup for capturing and classifying birdsong.

## Core Workflows
- **Recording loop:** `obsloop.sh` (systemd service) resolves the USB mic (Røde AI-Micro) with `arecord`, records hour-long stereo captures at 48 kHz, keeps a rolling 24-file cache in `stereo/`, stores mono FLACs under `raw/`, runs `BirdNET-Analyzer/analyze.py` with Parikkala coordinates, and ingests results into SQLite via `ingest_csv.py`. Analyzer CSVs go to a temp file and are deleted after ingestion.
- **Result review & clipping:** `.venv/bin/python species2.py` queries the SQLite database to list observations, filter by species/confidence/time, or create clips (`--clip`/`--clap`) via `sox`. The older `species.py` reads CSV files directly and is kept for reference.

## Data & Storage
- `birdnet.sqlite` — consolidated detection database (~10.5 M detections, ~23 k recordings, ~270 species). Read-only access via `species2.py`; writes via `ingest_csv.py`.
- `raw/` — untouched mono FLAC captures, periodically archived off-site. Large; avoid destructive edits.
- `res/` — legacy CSV outputs from BirdNET. No longer written to by the live pipeline (ingestion now uses temp files). Existing files kept as historical backup; do not delete without checking with the user.
- `stereo/` — rolling 24-hour cache of stereo recordings for listening/upload.
- `clips/` — optional audio excerpts created by `species2.py --clip`/`--clap`.
- `BirdNET-Analyzer/` — upstream analyzer code (not managed here).
- `experiments/` — local scratch area for various coding efforts.

## Key Scripts
- `obsloop.sh` — main recording loop (see Core Workflows).
- `ingest_csv.py` — parses BirdNET CSV results into SQLite. Idempotent (ON CONFLICT upserts). Resolves model version from `model-update-times.txt`.
- `species2.py` — SQLite-based observation viewer/clipper (replaces `species.py` for daily use).
- `species.py` — original CSV-based viewer (kept for reference; default confidence lowered to 0.8).
- `fix_timestamp_offsets.py` — one-off repair tool for early UTC-offset ingestion bugs.
- `resplots.R` — R script for temporal heatmap visualisation of detections.

## Environment
- Python lives in `.venv`; invoke as `.venv/bin/python …`. Package changes via `uv pip install …`.
- No automated tests — changes are exercised directly on the live pipeline.

## Operational Notes
- **Analyzer overlap:** `--overlap 1.5` splits the 3 s analysis windows into halves, producing offsets at 0, 1.5, 3, 4.5 s, etc.
- **48-week scheme:** `qweek = (month-1)*4 + (day-1)//7`, computed in `obsloop.sh` and `ingest_csv.py`. This is a BirdNET feature; verify after BirdNET updates.
- **Systemd service:** `obsloop.service` (`/etc/systemd/system/obsloop.service`) runs as user `pi` from `/home/pi/tirpat`. Reference copy in `systemd/`. After edits: `sudo cp systemd/obsloop.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl restart obsloop`.
- **Known false positives:** `docs/FAKES.txt` lists species frequently misidentified at this location (e.g. luhtahuitti = lake waves, viiksitimali = rain). Not yet filtered automatically (see `docs/TODO.txt`).
- **Model versions:** tracked in `model-update-times.txt`; `ingest_csv.py` assigns versions based on recording timestamp.
- **Raw audio** is large: prefer archiving before bulk processing, and avoid destructive edits within `raw/`.
