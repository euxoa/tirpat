#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import hashlib
import os
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

DEFAULT_DB = "birdnet.sqlite"
DEFAULT_RECENT_HOURS = 24.0


DSCR = """
Summarise BirdNET-Analyzer observations stored in the SQLite database.
Mirrors the original CSV-based species.py helper while keeping the DB read-only.
Optional positional patterns only filter recordings by basename; CSV files are not read.
"""

EPLG = """
Examples:

   # List detections from the default 24h window
   python species2.py

   # Only owls, filter by recording basename pattern (no CSV access)
   python species2.py --species 'owl|Strix' res/res-202406*_*.txt

   # Produce clips like the original helper
   python species2.py -l 60 -n 5 --full-only --clips raw clips-out
"""


def detect_local_timezone() -> str:
    """Best-effort local timezone guess (prefers Olson database names)."""
    tz_env = os.environ.get("TZ")
    if tz_env:
        return tz_env
    # Try /etc/timezone (Debian/Ubuntu)
    try:
        tz = Path("/etc/timezone").read_text().strip()
        if "/" in tz:
            return tz
    except OSError:
        pass
    # Try /etc/localtime symlink (most Linux distros)
    try:
        link = os.readlink("/etc/localtime")
        marker = "zoneinfo/"
        idx = link.find(marker)
        if idx != -1:
            return link[idx + len(marker):]
    except OSError:
        pass
    return "UTC"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=DSCR,
        epilog=EPLG,
        formatter_class=argparse.RawTextHelpFormatter,
        add_help=False,
    )
    parser.add_argument("-?", "--help", action="help", help="show this help message and exit")

    parser.add_argument("-p", "--pmin", type=float, default=0.8, help="confidence, minimum (default: 0.8)")
    parser.add_argument(
        "-l", "--minlag", type=float, default=2.0, help="seconds, min between adjacent included rows (default: 2.0)"
    )
    parser.add_argument("-n", "--nrows", type=int, default=3, help="max number of rows per species (default: 3)")
    parser.add_argument("--hours", "-h", type=float, help="limit detections to the last H hours")
    parser.add_argument(
        "--raw",
        action=argparse.BooleanOptionalAction,
        help="raw observations, skips ordering, argmax(p) logic and max number of lines",
    )
    parser.add_argument("--debug", action=argparse.BooleanOptionalAction, help="turn on some extra output")
    parser.add_argument(
        "--full-only", action=argparse.BooleanOptionalAction, help="require max number (nrows) of lines for species"
    )
    parser.add_argument(
        "--nonfull-only",
        action=argparse.BooleanOptionalAction,
        help="require less than max number (nrows) of lines for species",
    )
    parser.add_argument("--species", type=str, default="", help="species regex to filter with")
    parser.add_argument("--db", type=str, default=DEFAULT_DB, help=f"SQLite database file (default: {DEFAULT_DB})")
    parser.add_argument(
        "--output-duration", type=float, default=20, help="length of clips, in seconds (default: 20)"
    )
    parser.add_argument("--output-type", type=str, default="flac", help="type of clips, as recognised by sox")
    parser.add_argument(
        "--timezone",
        type=str,
        default=detect_local_timezone(),
        help="time zone for species lists and clip names (UTC in clip metadata)",
    )
    parser.add_argument("--clip", nargs=2, metavar=("RAW_DIR", "CLIP_DIR"), help="dir of orig. audio and dir of clips")
    parser.add_argument(
        "--clap",
        action=argparse.BooleanOptionalAction,
        help="clip, assuming origs are in 'raw' and clips are in 'clips'",
    )
    parser.add_argument("--counts", action=argparse.BooleanOptionalAction, help="accepted obs counts per species")
    parser.add_argument(
        "input_patterns",
        nargs="*",
        help="optional glob patterns or basenames (e.g. res/res-*.txt) to filter recordings by basename only",
    )
    return parser


def deduplicate2(df: pd.DataFrame, var: str, threshold, var_max: str) -> pd.DataFrame:
    """
    Collapse neighbouring rows closer than threshold (by column `var`) by taking the row
    with the highest `var_max` value within each cluster.
    """
    df = df.sort_values(var)
    cluster_id = (~df[var].diff(periods=1).abs().lt(threshold).values).cumsum()
    return df.groupby(cluster_id, group_keys=False).apply(lambda grp: grp.nlargest(1, var_max)).reset_index(drop=True)


def resolve_input_basenames(patterns: list[str]) -> list[str]:
    basenames: set[str] = set()
    for pattern in patterns:
        candidate = Path(pattern)
        matched = False
        if candidate.is_dir():
            for entry in sorted(candidate.glob("*.txt")):
                basenames.add(entry.name)
            matched = True
        else:
            for match in sorted(glob.glob(pattern)):
                mp = Path(match)
                if mp.is_dir():
                    for entry in sorted(mp.glob("*.txt")):
                        basenames.add(entry.name)
                else:
                    basenames.add(mp.name)
                matched = True
        if not matched:
            basenames.add(candidate.name)
    return sorted(basenames)


def resolve_species_ids(conn: sqlite3.Connection, pattern: str) -> list[int]:
    try:
        rex = re.compile(pattern)
    except re.error as exc:
        raise SystemExit(f"Invalid species regex '{pattern}': {exc}") from exc
    cursor = conn.execute("SELECT species_id, sci_name, common_name FROM species")
    matches: list[int] = []
    for row in cursor:
        sci = row["sci_name"]
        common = row["common_name"]
        if (sci and rex.search(sci)) or (common and rex.search(common)):
            matches.append(row["species_id"])
    cursor.close()
    return matches


def fetch_detections(
    conn: sqlite3.Connection,
    *,
    pmin: float,
    hours: float | None,
    basenames: list[str],
    species_ids: list[int] | None,
) -> pd.DataFrame:
    params: list[object] = [pmin]
    conditions = ["d.confidence >= ?"]

    if hours is not None and hours > 0:
        since_ts = int(time.time() - hours * 3600)
        conditions.append("d.ts_utc >= ?")
        params.append(since_ts)

    basenames_in_sql = basenames and len(basenames) <= 900
    if basenames_in_sql:
        placeholders = ",".join(["?"] * len(basenames))
        conditions.append(f"r.file_basename IN ({placeholders})")
        params.extend(basenames)

    if species_ids:
        placeholders = ",".join(["?"] * len(species_ids))
        conditions.append(f"d.species_id IN ({placeholders})")
        params.extend(species_ids)

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    query = f"""
        SELECT
            d.detection_id,
            d.ts_utc,
            d.offset_start_s AS start,
            d.dur_s AS duration,
            d.confidence AS p,
            s.sci_name AS species,
            s.common_name AS cname,
            r.file_basename AS file,
            r.ts_start_utc,
            r.station_id,
            d.model_version,
            d.clip_hint,
            d.notes
        FROM detections d
        JOIN species s ON s.species_id = d.species_id
        JOIN recordings r ON r.recording_id = d.recording_id
        WHERE {where_clause}
        ORDER BY d.ts_utc ASC
    """

    df = pd.read_sql_query(query, conn, params=params)

    if basenames and not basenames_in_sql:
        df = df[df["file"].isin(basenames)]

    return df


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        sys.stderr.write(f"Database not found: {db_path}\n")
        sys.exit(1)

    species_ids: list[int] | None = None
    basenames = resolve_input_basenames(args.input_patterns)
    hours = args.hours
    if hours is None and not basenames:
        hours = DEFAULT_RECENT_HOURS
        if args.debug:
            sys.stderr.write(
                f"No filters provided; defaulting to last {hours} hours (override with --hours, 0 for all).\n"
            )

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        if args.species:
            species_ids = resolve_species_ids(conn, args.species)
            if args.debug:
                sys.stderr.write(f"Species filter matched {len(species_ids)} species.\n")
            if not species_ids:
                print("No species matched the regex filter.")
                return
        detections = fetch_detections(
            conn,
            pmin=args.pmin,
            hours=hours,
            basenames=basenames,
            species_ids=species_ids,
        )
    finally:
        conn.close()

    if detections.empty:
        print("No detections matched filters.")
        return

    if args.debug:
        sys.stderr.write(f"Fetched {len(detections)} detections.\n")

    detections = detections.copy()
    detections["end"] = detections["start"] + detections["duration"]
    detections["t_center"] = detections["start"] + detections["duration"] / 2.0
    detections["t"] = pd.to_datetime(detections["ts_start_utc"], unit="s", utc=True) + pd.to_timedelta(
        detections["t_center"], unit="s"
    )

    if args.debug:
        sys.stderr.write("Deduplicating per species with minimum lag.\n")
    threshold = pd.to_timedelta(args.minlag, unit="s")
    deduped_parts = []
    for _, group in detections.groupby("species", sort=False):
        deduped_parts.append(deduplicate2(group, "t", threshold, "p"))
    if deduped_parts:
        deduped = pd.concat(deduped_parts, ignore_index=True)
    else:
        deduped = detections.iloc[0:0].copy()

    if args.debug:
        sys.stderr.write("Computing counts.\n")
    counts_df = deduped.groupby("species", as_index=False).size().rename(columns={"size": "count"})

    if args.raw:
        samples = detections
    else:
        sample_parts = []
        for _, group in deduped.groupby("species", sort=False):
            sample_parts.append(group.sort_values("p", ascending=False).head(args.nrows))
        samples = pd.concat(sample_parts, ignore_index=True) if sample_parts else deduped.iloc[0:0].copy()

    if args.full_only:
        samples = samples.groupby("species").filter(lambda x: x.shape[0] == args.nrows)
    if args.nonfull_only:
        samples = samples.groupby("species").filter(lambda x: x.shape[0] < args.nrows)

    if samples.empty:
        print("No detections matched filters.")
        return

    if args.debug:
        sys.stderr.write("Formatting timestamps.\n")
    samples["nicetime"] = samples.t.dt.tz_convert(args.timezone).dt.strftime("%A %d.%m.%Y %H:%M")
    samples["utctime"] = samples.t.dt.strftime("%Y-%m-%d %H:%M UTC")
    samples["nicetime2"] = samples.t.dt.tz_convert(args.timezone).dt.strftime("%Y%m%d_%H%M")

    if args.clap:
        do_clip, raw_dir, clip_dir = True, "raw", "clips"
    elif args.clip is not None:
        do_clip, raw_dir, clip_dir = True, args.clip[0], args.clip[1]
    else:
        do_clip, raw_dir, clip_dir = False, None, None

    if not do_clip:
        if args.counts:
            to_show = (
                samples.groupby(["species", "cname"], as_index=False)["p"]
                .max()
                .merge(counts_df, on="species")
                .sort_values("count", ascending=False)
            )
        else:
            to_show = samples.loc[:, ("species", "cname", "p", "nicetime")]
        print(to_show.to_string(index=False))
        return

    date_ptrn = re.compile(r"(\d{8}_\d{6})")
    try:
        samples["file_ptrn"] = [re.search(date_ptrn, file).group(1) for file in samples["file"]]
    except AttributeError as exc:
        raise RuntimeError("Found recording filename without timestamp pattern") from exc

    raw_map = {re.search(date_ptrn, Path(file).name).group(1): file for file in glob.glob(f"{raw_dir}/*")}

    for _, row in samples.iterrows():
        orig = raw_map.get(row["file_ptrn"])
        if not orig:
            print("No raw match for", row["file"])
            continue
        tmax = float(
            subprocess.run(["soxi", "-D", orig], stdout=subprocess.PIPE, text=True, check=True).stdout.strip() or 0
        )
        start = float(row["start"])
        p = float(row["p"])
        species = row["species"]
        utctime = row["utctime"]
        t_center = float(row["t_center"])
        nicetime2 = row["nicetime2"]
        comment = (
            f"species={species}, confidence={p}, time={utctime}, orig_file={orig}, t_center={t_center}"
        )
        hsh = f"{int(100 * p)}{hashlib.md5(comment.encode('latin1')).hexdigest()[:2]}"
        clip_path = f"{clip_dir}/{row['cname']}_{nicetime2}_{hsh}.{args.output_type}"
        half = args.output_duration / 2.0
        virt0 = t_center - half
        virt1 = t_center + half
        t0 = virt0 if virt0 > 0 else 0
        pad0 = 0 if virt0 > 0 else -virt0
        t1 = virt1 if virt1 < tmax else tmax
        pad1 = 0 if virt1 < tmax else virt1 - tmax
        print(f"Clipping {orig} to {clip_path}, @{t_center} pads {pad0} {pad1}")
        sox1 = subprocess.Popen(
            [
                "sox",
                orig,
                "-t",
                "flac",
                "-",
                "trim",
                str(t0),
                str(t1 - t0),
                "highpass",
                "100",
                "norm",
                "-4",
            ],
            stdout=subprocess.PIPE,
        )
        subprocess.run(
            [
                "sox",
                "-",
                "--comment",
                comment,
                "-b",
                "16",
                clip_path,
                "pad",
                str(pad0),
                str(pad1),
            ],
            stdin=sox1.stdout,
            check=True,
        )


if __name__ == "__main__":
    main()
