import os
import sys
import json
import logging
import argparse
import numpy as np

from math import radians, cos, sin, asin, sqrt
from collections import defaultdict
from sqlalchemy import create_engine, desc
from sqlalchemy.orm import sessionmaker
from shapely.geometry import Point, Polygon

import migrate

logger = logging.getLogger(__name__)

# --- DB setup (identical to dataProcessor.py) ---
user     = os.getenv('DB_USER', 'neondb_owner')
password = os.getenv('DB_PASSWORD')
db_host  = os.getenv('DB_HOST')
db_name  = os.getenv('DB_NAME', 'neondb')
db_opts  = os.getenv('DB_OPTIONS', 'sslmode=disable')

db_url = f"postgresql://{user}:{password}@{db_host}/{db_name}?{db_opts}"
engine = create_engine(db_url)
Session = sessionmaker(bind=engine)
db = Session()

# --- Config ---
BIN_SIZE_KM    = 5
MAX_DIST_KM    = 400
MIN_SPEED_KPH  = 30   # below this = taxiing / noise
MIN_BIN_SAMPLES = 5   # minimum points to trust a bin median


def haversine(lon1, lat1, lon2, lat2):
    """Matches dataProcessor.py signature exactly: lon1, lat1, lon2, lat2"""
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    dlon, dlat = lon2 - lon1, lat2 - lat1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    return 6371 * 2 * asin(sqrt(a))


def load_roi_polygons():
    """Load all level-2 fire ROIs as Shapely polygons."""
    rois = db.query(migrate.RegionOfInterest).filter(
        migrate.RegionOfInterest.level == 2,
        migrate.RegionOfInterest.type == 'fire',
        migrate.RegionOfInterest.geometry.isnot(None)
    ).all()

    polygons = []
    for roi in rois:
        try:
            coords = json.loads(roi.geometry)
            if len(coords) >= 3:
                polygons.append(Polygon(coords))  # [lat,lon] space, matches dataProcessor.py
        except (TypeError, ValueError) as e:
            logger.warning(f"Skipping ROI {roi.id}: {e}")
    logger.info(f"Loaded {len(polygons)} level-2 fire ROIs")
    return polygons


def load_airfields():
    """Return dict: icao -> (lat, lon)"""
    airfields = db.query(migrate.Airfield).all()
    return {af.icao: (af.lat, af.lon, af.name) for af in airfields}


def is_in_roi(lat, lon, roi_polygons):
    """Check if point is inside any ROI. Uses [lat,lon] space like dataProcessor.py"""
    pt = Point(lat, lon)
    return any(p.contains(pt) for p in roi_polygons)


def get_home_base_per_aircraft(water_bombers_icao24s):
    """
    Derive home base = most frequent departure airfield per icao24.
    Departure = at_airfield flips False after being True.
    Returns dict: icao24 -> airfield_icao
    """
    logger.info("Computing home bases from departure history...")

    # Raw SQL is cleaner here for the window function
    from sqlalchemy import text
    query = text("""
        WITH transitions AS (
            SELECT
                icao24,
                latest_airfield,
                at_airfield,
                LAG(at_airfield) OVER (
                    PARTITION BY icao24 ORDER BY timestamp
                ) AS prev_at_airfield
            FROM flight_telemetry
            WHERE icao24 = ANY(:icao_list)
              AND latest_airfield IS NOT NULL
        ),
        departures AS (
            SELECT icao24, latest_airfield
            FROM transitions
            WHERE at_airfield = FALSE
              AND prev_at_airfield = TRUE
        ),
        ranked AS (
            SELECT
                icao24,
                latest_airfield,
                COUNT(*) AS cnt,
                ROW_NUMBER() OVER (
                    PARTITION BY icao24 ORDER BY COUNT(*) DESC
                ) AS rn
            FROM departures
            GROUP BY icao24, latest_airfield
        )
        SELECT icao24, latest_airfield
        FROM ranked
        WHERE rn = 1
    """)

    result = db.execute(query, {"icao_list": list(water_bombers_icao24s)})
    home_bases = {row.icao24: row.latest_airfield for row in result}
    logger.info(f"Found home bases for {len(home_bases)} aircraft")
    return home_bases


def extract_outbound_legs(roi_polygons, airfields, home_bases, aircraft_models):
    """
    For each aircraft, find all outbound legs:
    takeoff (at_airfield False after True) → first is_low_pass=True inside level-2 ROI
    Returns list of legs, each a list of telemetry dicts with dist_from_base_km added.
    """
    legs = []
    icao_list = list(home_bases.keys())

    for icao24 in icao_list:
        model = aircraft_models.get(icao24)
        if not model:
            logger.debug(f"No model for {icao24}, skipping")
            continue

        home_icao = home_bases[icao24]
        if home_icao not in airfields:
            logger.debug(f"Airfield {home_icao} not in DB, skipping {icao24}")
            continue

        base_lat, base_lon, base_name = airfields[home_icao]

        # Pull full telemetry for this aircraft, ordered by time
        records = db.query(migrate.FlightTelemetry).filter(
            migrate.FlightTelemetry.icao24 == icao24,
            migrate.FlightTelemetry.speed_kph.isnot(None),
            migrate.FlightTelemetry.lat.isnot(None),
            migrate.FlightTelemetry.lon.isnot(None)
        ).order_by(migrate.FlightTelemetry.timestamp.asc()).all()

        if len(records) < 5:
            continue

        # Detect flights: segment on at_airfield transitions
        in_flight    = False
        current_leg  = []
        leg_count    = 0

        for i, rec in enumerate(records):
            prev_at_airfield = records[i-1].at_airfield if i > 0 else True

            # Takeoff detected
            if not rec.at_airfield and prev_at_airfield:
                in_flight    = True
                current_leg  = []

            if in_flight and not rec.at_airfield:
                current_leg.append(rec)

                # Termination: low pass inside a level-2 ROI
                if rec.is_low_pass and is_in_roi(rec.lat, rec.lon, roi_polygons):
                    # Valid outbound leg found
                    if len(current_leg) >= 3:
                        leg_with_dist = []
                        for r in current_leg:
                            dist = haversine(base_lon, base_lat, r.lon, r.lat)
                            leg_with_dist.append({
                                'dist_km':   dist,
                                'speed_kph': r.speed_kph,
                                'model':     model
                            })
                        legs.append(leg_with_dist)
                        leg_count += 1
                    in_flight   = False
                    current_leg = []

            # Landing resets state
            if rec.at_airfield and in_flight:
                in_flight   = False
                current_leg = []

        logger.debug(f"{icao24} ({model}): {leg_count} outbound legs extracted")

    logger.info(f"Total outbound legs extracted: {len(legs)}")
    return legs


def build_speed_profiles(legs):
    """
    Bin speeds by distance from base, aggregate median per aircraft_model.
    Returns dict: model -> list of (distance_km, median_speed_kph, sample_count)
    """
    # model -> bin_index -> [speeds]
    bins = defaultdict(lambda: defaultdict(list))

    for leg in legs:
        for point in leg:
            if point['speed_kph'] < MIN_SPEED_KPH:
                continue
            bin_idx = int(point['dist_km'] / BIN_SIZE_KM)
            if bin_idx == 0:  # skip — aircraft still at/near base
                continue
            if bin_idx * BIN_SIZE_KM > MAX_DIST_KM:
                continue
            bins[point['model']][bin_idx].append(point['speed_kph'])

    profiles = {}
    for model, model_bins in bins.items():
        profile = []
        for bin_idx in sorted(model_bins.keys()):
            speeds = model_bins[bin_idx]
            if len(speeds) >= MIN_BIN_SAMPLES:
                profile.append({
                    'distance_km':      bin_idx * BIN_SIZE_KM,
                    'median_speed_kph': round(float(np.median(speeds)), 1),
                    'sample_count':     len(speeds)
                })
        if profile:
            profiles[model] = profile

    return profiles


def print_profiles(profiles):
    for model, profile in sorted(profiles.items()):
        total_samples = sum(p['sample_count'] for p in profile)
        print(f"\n{model} ({total_samples} total samples):")
        print(f"  {'Distance':>10}  {'Median speed':>14}  {'Samples':>8}")
        print(f"  {'-'*38}")
        for p in profile:
            print(f"  {p['distance_km']:>8.0f}km  "
                  f"{p['median_speed_kph']:>11.1f}kph  "
                  f"{p['sample_count']:>8}")


def save_profiles(profiles, path='speed_profiles.json'):
    with open(path, 'w') as f:
        json.dump(profiles, f, indent=2)
    logger.info(f"Speed profiles saved to {path}")


if __name__ == "__main__":
    LOG_FORMAT = "%(asctime)s [%(levelname)s] [%(filename)s:%(lineno)d] %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=LOG_FORMAT,
        datefmt="%H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)]
    )

    parser = argparse.ArgumentParser(description="Build per-model speed profiles from SkyWatch telemetry")
    parser.add_argument('--output', default='speed_profiles.json',
                        help='Output JSON file path (default: speed_profiles.json)')
    parser.add_argument('--bin-size', type=int, default=BIN_SIZE_KM,
                        help=f'Distance bin size in km (default: {BIN_SIZE_KM})')
    parser.add_argument('--max-dist', type=int, default=MAX_DIST_KM,
                        help=f'Max distance to profile in km (default: {MAX_DIST_KM})')
    args = parser.parse_args()

    BIN_SIZE_KM = args.bin_size
    MAX_DIST_KM = args.max_dist

    # 1. Load reference data
    roi_polygons = load_roi_polygons()
    airfields    = load_airfields()

    # 2. Get water bombers with their models
    water_bombers = db.query(
        migrate.TrackedAircraft.icao24,
        migrate.TrackedAircraft.aircraft_model
    ).filter(
        migrate.TrackedAircraft.payload_capacity_kg > 0,
        migrate.TrackedAircraft.aircraft_model.isnot(None)
    ).all()

    aircraft_models   = {ac.icao24: ac.aircraft_model for ac in water_bombers}
    water_bomber_icao = set(aircraft_models.keys())
    logger.info(f"Found {len(water_bomber_icao)} water bombers across "
                f"{len(set(aircraft_models.values()))} models")

    # 3. Derive home bases
    home_bases = get_home_base_per_aircraft(water_bomber_icao)

    # 4. Extract outbound legs
    legs = extract_outbound_legs(roi_polygons, airfields, home_bases, aircraft_models)

    if not legs:
        logger.error("No outbound legs found — check ROI data and telemetry coverage")
        sys.exit(1)

    # 5. Build and display profiles
    profiles = build_speed_profiles(legs)
    print_profiles(profiles)

    # 6. Save for use by heatmap engine
    save_profiles(profiles, args.output)