# species2.py SQL Delegation Notes

## Current Split Of Work
- `species2.py` pushes coarse filters into SQLite: confidence threshold, optional time window (`--hours`), recording basename patterns, and species IDs matched in the `species` table.
- The script keeps the per-species spacing (`--minlag`), best-`n` selection, and clip preparation in Python/Pandas, mirroring the legacy CSV workflow.

## Why Not Push More Into SQL?
- **Regex flexibility** – SQLite lacks native regex support. Registering a custom `REGEXP` UDF would complicate deployment and still miss Python’s richer regex flags. Instead we match regexes in Python once against the `species` table and send the resulting IDs to SQL.
- **Minlag sparsening** – Replicating the “keep the highest-confidence hit per ≥`minlag` gap” logic in SQL needs window functions or recursive CTEs. SQLite can do it, but the SQL becomes hard to read and maintain, and gains are tiny now that we fetch only the time-windowed subset.
- **Top-N per species** – SQLite could assign `ROW_NUMBER()` per species, yet we would still need the spacing pass first. Doing the ranking in Pandas keeps the code close to the original behaviour and avoids multi-pass SQL.
- **Clip prep** – Downstream steps (timestamp formatting, `sox` invocations, hash generation) are inherently Python-side, so pushing more into SQL would not eliminate the Pandas dependency.

## When To Revisit
- If performance regresses even with the `detections_ts_idx` index and a reasonable `--hours` window, consider prototyping a window-function query that performs the spacing and ranking in SQL.
- If we ever require deterministic server-side filtering (e.g., exposing the DB via an API), port the logic carefully and add tests to ensure parity with the Python reference.
