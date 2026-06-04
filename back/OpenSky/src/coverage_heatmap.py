"""
Radar Coverage Heatmap
======================
Analyses gaps between consecutive telemetry points to infer radar coverage quality.

Logic
-----
For each pair of consecutive *airborne* points from the same aircraft:
  - gap_s   = p2.timestamp - p1.timestamp
  - midpoint lat/lon is attributed that gap
  - avg AGL altitude → one of three fixed altitude bands

Metric stored per grid cell: median gap in seconds.
  Low  value → aircraft seen frequently → good coverage
  High value → large holes between detections → poor coverage

Gaps below MIN_GAP_S are excluded (normal ADS-B poll rate, not informative).
Gaps above MAX_GAP_S are excluded (aircraft likely powered off, not a coverage gap).

If a cell has no data in a higher band it inherits from the nearest lower band
(radar coverage changes slowly with altitude).

Altitude bands
--------------
  coverage_1000ft.json       →  0 – 1000 ft AGL
  coverage_2000ft.json       →  1000 – 2000 ft AGL
  coverage_3000ft.json       →  2000 – 3000 ft AGL
  coverage_4000ft.json       →  3000 – 4000 ft AGL
  coverage_5000ft.json       →  4000 – 5000 ft AGL
  coverage_6000ft.json       →  5000 – 6000 ft AGL
  coverage_7000ft.json       →  6000 – 7000 ft AGL
  coverage_above7000ft.json  →  above 7000 ft AGL

Run
---
  python coverage_heatmap.py --days 90

All env vars (DB_USER, DB_PASSWORD, DB_HOST, DB_NAME, HEATMAP_DIR) are read from
the environment — same as the other scripts.
"""

import os
import sys
import json
import logging
import argparse
import numpy as np
from math import radians, cos
from datetime import datetime, timedelta
from collections import defaultdict

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import migrate

logger = logging.getLogger(__name__)

# ── DB ────────────────────────────────────────────────────────────────────────
db_url = (
    f"postgresql://{os.getenv('DB_USER','neondb_owner')}:{os.getenv('DB_PASSWORD')}"
    f"@{os.getenv('DB_HOST')}/{os.getenv('DB_NAME','neondb')}"
    f"?{os.getenv('DB_OPTIONS','sslmode=disable')}"
)
engine  = create_engine(db_url)
Session = sessionmaker(bind=engine)
db      = Session()

KM_PER_DEG_LAT = 111.0

# ── Altitude bands ────────────────────────────────────────────────────────────
# (bottom_ft_inclusive, top_ft_exclusive_or_None, file_suffix, display_label)
BANDS = [
    (    0, 1000, "1000ft",       "0 – 1000 ft"),
    ( 1000, 2000, "2000ft",       "1000 – 2000 ft"),
    ( 2000, 3000, "3000ft",       "2000 – 3000 ft"),
    ( 3000, 4000, "4000ft",       "3000 – 4000 ft"),
    ( 4000, 5000, "5000ft",       "4000 – 5000 ft"),
    ( 5000, 6000, "6000ft",       "5000 – 6000 ft"),
    ( 6000, 7000, "7000ft",       "6000 – 7000 ft"),
    ( 7000, None, "above7000ft",  "above 7000 ft"),
]

def assign_band(agl_ft):
    """Return the BANDS entry for the given AGL altitude, or None if below lowest band."""
    for entry in BANDS:
        bot, top, suffix, label = entry
        if agl_ft >= bot and (top is None or agl_ft < top):
            return entry
    return None


# ── Grid helpers ──────────────────────────────────────────────────────────────

def build_grid(lat_min, lat_max, lon_min, lon_max, grid_km):
    mid_lat  = (lat_min + lat_max) / 2
    step_lat = grid_km / KM_PER_DEG_LAT
    step_lon = grid_km / (KM_PER_DEG_LAT * cos(radians(mid_lat)))

    lats, lat = [], lat_min
    while lat <= lat_max + step_lat * 0.5:
        lats.append(round(lat, 5)); lat += step_lat

    lons, lon = [], lon_min
    while lon <= lon_max + step_lon * 0.5:
        lons.append(round(lon, 5)); lon += step_lon

    return lats, lons, step_lat, step_lon


def snap_to_grid(value, origin, step):
    """Round value to nearest grid line starting from origin."""
    return round(origin + round((value - origin) / step) * step, 5)


def fill_neighbors(values, rows, cols, max_passes=1):
    """
    Fill null cells by estimating from non-null 8-neighbours with distance decay.
    Each neighbour contributes its value + distance_in_pixels (1 s per orthogonal
    step, √2 s per diagonal step).  The filled cell takes the mean of all
    available decayed estimates, so quality degrades the further from real data.
    Multiple passes compound: a cell 3 hops from the nearest observation gets
    roughly +3 s added to the source value.
    Cells with no reachable neighbours within max_passes steps remain null.
    """
    SQRT2 = np.sqrt(2)
    # (row_offset, col_offset, distance_penalty_seconds)
    OFFSETS = [
        (-1, -1, 3.0 * SQRT2), (-1, 0, 3.0), (-1, 1, 3.0 * SQRT2),
        ( 0, -1, 3.0),                         ( 0, 1, 3.0),
        ( 1, -1, 3.0 * SQRT2), ( 1, 0, 3.0), ( 1, 1, 3.0 * SQRT2),
    ]

    grid = np.array([v if v is not None else np.nan for v in values],
                    dtype=float).reshape(rows, cols)

    for _ in range(max_passes):
        nan_mask = np.isnan(grid)
        if not nan_mask.any():
            break

        nbr_sum   = np.zeros((rows, cols))
        nbr_count = np.zeros((rows, cols))

        for dr, dc, dist in OFFSETS:
            shifted = np.roll(np.roll(grid, dr, axis=0), dc, axis=1)
            # Mask wrapped edges
            if dr == -1: shifted[-1, :] = np.nan
            elif dr ==  1: shifted[ 0, :] = np.nan
            if dc == -1: shifted[:, -1]  = np.nan
            elif dc ==  1: shifted[:,  0]  = np.nan

            valid = ~np.isnan(shifted)
            nbr_sum   += np.where(valid, shifted + dist, 0.0)  # apply decay
            nbr_count += valid.astype(float)

        fill_mask = nan_mask & (nbr_count > 0)
        grid = np.where(fill_mask, nbr_sum / np.maximum(nbr_count, 1), grid)

    flat = grid.flatten().tolist()
    return [round(v, 1) if not np.isnan(v) else None for v in flat]


def to_compact_grid(gap_grid, lats, lons, step_lat, step_lon, band_bottom, band_top, band_label):
    values = []
    for lat in sorted(lats, reverse=True):
        for lon in sorted(lons):
            gaps = gap_grid.get((lat, lon), [])
            values.append(round(float(np.median(gaps)), 1) if gaps else None)

    rows, cols = len(lats), len(lons)
    values = fill_neighbors(values, rows, cols)

    covered = sum(1 for v in values if v is not None)
    return {
        "metadata": {
            "generated_at":    datetime.now().isoformat(),
            "type":            "radar_coverage",
            "alt_band_ft":     band_bottom,
            "alt_band_top_ft": band_top,          # None means unlimited
            "alt_band_label":  band_label,
            "lat_min":         round(min(lats), 5),
            "lat_max":         round(max(lats), 5),
            "lon_min":         round(min(lons), 5),
            "lon_max":         round(max(lons), 5),
            "step_lat":        round(step_lat, 6),
            "step_lon":        round(step_lon, 6),
            "rows":            len(lats),
            "cols":            len(lons),
            "total_cells":     len(values),
            "covered_cells":   covered,
            "metric":          "median_gap_seconds",
        },
        "values": values,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    parser = argparse.ArgumentParser(description="Radar coverage heatmap by altitude band")
    parser.add_argument("--days",       type=int,   default=90,   help="Days of telemetry to analyse (default: 90)")
    parser.add_argument("--min-gap",    type=int,   default=15,   help="Minimum gap to record in seconds (default: 15)")
    parser.add_argument("--max-gap",    type=int,   default=300,  help="Maximum gap cap in seconds (default: 300)")
    parser.add_argument("--grid-km",    type=float, default=1.0,  help="Grid cell size in km (default: 1.0)")
    parser.add_argument("--output-dir", default=None,             help="Output directory (default: $HEATMAP_DIR or .)")
    args = parser.parse_args()

    output_dir = args.output_dir or os.getenv("HEATMAP_DIR", ".")

    # ── 1. Fetch telemetry ───────────────────────────────────────────────────
    cutoff = int((datetime.now() - timedelta(days=args.days)).timestamp())
    logger.info(f"Querying last {args.days} days of processed airborne telemetry...")

    rows = (
        db.query(
            migrate.FlightTelemetry.icao24,
            migrate.FlightTelemetry.timestamp,
            migrate.FlightTelemetry.lat,
            migrate.FlightTelemetry.lon,
            migrate.FlightTelemetry.altitude_agl_ft,
        )
        .filter(
            migrate.FlightTelemetry.is_processed      == True,
            migrate.FlightTelemetry.on_ground         == False,
            migrate.FlightTelemetry.lat.isnot(None),
            migrate.FlightTelemetry.lon.isnot(None),
            migrate.FlightTelemetry.altitude_agl_ft.isnot(None),
            migrate.FlightTelemetry.altitude_agl_ft   <  60000,   # exclude sentinel
            migrate.FlightTelemetry.timestamp         >= cutoff,
        )
        .order_by(migrate.FlightTelemetry.icao24, migrate.FlightTelemetry.timestamp)
        .all()
    )
    logger.info(f"Loaded {len(rows):,} telemetry points across "
                f"{len(set(r.icao24 for r in rows))} aircraft")

    if not rows:
        logger.error("No data found — check filters or increase --days")
        sys.exit(1)

    # ── 2. Bounding box ──────────────────────────────────────────────────────
    all_lats = [r.lat for r in rows]
    all_lons = [r.lon for r in rows]
    lat_min, lat_max = min(all_lats), max(all_lats)
    lon_min, lon_max = min(all_lons), max(all_lons)
    logger.info(f"Bounding box: lat [{lat_min:.3f}, {lat_max:.3f}]  "
                f"lon [{lon_min:.3f}, {lon_max:.3f}]")

    # ── 3. Build grid ────────────────────────────────────────────────────────
    lats, lons, step_lat, step_lon = build_grid(
        lat_min, lat_max, lon_min, lon_max, args.grid_km
    )
    logger.info(f"Grid: {len(lats)} rows × {len(lons)} cols = "
                f"{len(lats) * len(lons):,} cells  (cell={args.grid_km} km)")

    # ── 4. Accumulate gaps per (band_suffix, cell) ───────────────────────────
    # gap_data[band_suffix][(snap_lat, snap_lon)] = [gap_s, ...]
    gap_data = defaultdict(lambda: defaultdict(list))

    by_aircraft = defaultdict(list)
    for r in rows:
        by_aircraft[r.icao24].append(r)

    total_gaps = recorded = skipped = 0
    for icao24, pts in by_aircraft.items():
        for i in range(len(pts) - 1):
            p1, p2 = pts[i], pts[i + 1]
            dt = p2.timestamp - p1.timestamp
            total_gaps += 1

            if dt < args.min_gap or dt > args.max_gap:
                skipped += 1
                continue

            avg_agl  = (p1.altitude_agl_ft + p2.altitude_agl_ft) / 2.0
            band_info = assign_band(avg_agl)
            if band_info is None:
                skipped += 1
                continue

            _, _, suffix, _ = band_info
            mid_lat = snap_to_grid((p1.lat + p2.lat) / 2.0, lat_min, step_lat)
            mid_lon = snap_to_grid((p1.lon + p2.lon) / 2.0, lon_min, step_lon)

            gap_data[suffix][(mid_lat, mid_lon)].append(dt)
            recorded += 1

    logger.info(f"Gaps: {total_gaps:,} total / {recorded:,} recorded / {skipped:,} skipped")
    logger.info(f"Altitude bands with data: {[s for _,_,s,_ in BANDS if s in gap_data]}")

    # ── 4b. Propagate coverage upward ────────────────────────────────────────
    # If a cell has no data in a higher band, inherit from the nearest lower band.
    all_cells = set()
    for band_cells in gap_data.values():
        all_cells.update(band_cells.keys())

    propagated = 0
    for cell in all_cells:
        last_data = None
        for _, _, suffix, _ in BANDS:   # iterate low → high
            cell_data = gap_data[suffix].get(cell)
            if cell_data:
                last_data = cell_data
            elif last_data is not None:
                gap_data[suffix][cell] = last_data
                propagated += 1

    logger.info(f"Propagated {propagated:,} cells upward from lower altitude bands")

    # ── 5. Write one JSON per altitude band ──────────────────────────────────
    written = 0
    for bot, top, suffix, label in BANDS:
        grid    = to_compact_grid(gap_data[suffix], lats, lons, step_lat, step_lon, bot, top, label)
        covered = grid["metadata"]["covered_cells"]
        if covered == 0:
            logger.info(f"  {label:<20}  →  no data, skipped")
            continue

        path = os.path.join(output_dir, f"heatmap_coverage_{suffix}.json")
        with open(path, "w") as fh:
            json.dump(grid, fh, separators=(",", ":"))
        logger.info(f"  {label:<20}  →  {covered:>5} cells  →  {path}")
        written += 1

    logger.info(f"Done — {written} file(s) written to {output_dir}")
