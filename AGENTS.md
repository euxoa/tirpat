# AGENTS

## Purpose
- Personal BirdNET installation deployed at a summer cottage in Parikkala; long-running bare-bones setup for capturing and classifying birdsong.

## Core Workflows
- Recording loop: `obsloop.sh` (systemd service) resolves the USB mic with `arecord`, records hour-long stereo captures, keeps a rolling cache in `stereo/`, stores mono FLACs under `raw/`, and invokes `BirdNET-Analyzer/analyze.py` with Parikkala coordinates to write CSV summaries in `res/`.
- Result review & clipping: run `.venv/bin/python species.py res/res-*` to list observations, filter by species/confidence, or create downsized clips (`--clip`/`--clap`) via `sox`.

## Layout & Data
- `raw/` holds untouched FLAC captures that are periodically archived off-site; `res/` collects analyzer CSV outputs; `clips/` is where optional excerpts land.
- `BirdNET-Analyzer/` contains the upstream analyzer code; other folders (`experiments/` for various coding efforts, `stereo/` for stereo audio files to be uploaded and listened, etc.) are local scratch areas. 

## Environment
- Python lives in `.venv`; invoke interpreters as `.venv/bin/python …`. Package changes go through `uv pip install …`.
- No automated tests—changes are exercised directly on the live pipeline.

## Operational Notes
- Analyzer week indices use the custom 48-week scheme computed in `obsloop.sh`; adjust with care. (This is a BirdNET feature; if BirdNET is updated, check if this still holds!)
- Raw audio is large: prefer archiving before bulk processing, and avoid destructive edits within `raw/`.
- `res/` have all the valuable analysis results, do not touch without double-checking the with user.
- Systemd service keeps the loop running: `obsloop.service` (`/etc/systemd/system/obsloop.service`) runs as user `pi` from `/home/pi/tirpat`. Use `sudo systemctl status obsloop`, `sudo systemctl restart obsloop`, and `journalctl -u obsloop` to monitor or restart it.
- Reference copy of the unit lives in `systemd/obsloop.service`; after edits, `sudo cp` to `/etc/systemd/system/obsloop.service && sudo systemctl daemon-reload` before restarting.
