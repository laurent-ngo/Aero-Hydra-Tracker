import os
import sys
import json
import logging
import argparse
import re
import numpy as np
from math import radians, cos, sin, asin, sqrt, ceil
from datetime import datetime, timedelta
from sqlalchemy import create_engine, desc
from sqlalchemy.orm import sessionmaker

import migrate

logger = logging.getLogger(__name__)

# --- DB setup ---
user     = os.getenv('DB_USER', 'neondb_owner')
password = os.getenv('DB_PASSWORD')
db_host  = os.getenv('DB_HOST')
db_name  = os.getenv('DB_NAME', 'neondb')
db_opts  = os.getenv('DB_OPTIONS', 'sslmode=disable')

db_url = f"postgresql://{user}:{password}@{db_host}/{db_name}?{db_opts}"
engine = create_engine(db_url)
Session = sessionmaker(bind=engine)
db = Session()

GRID_SIZE_KM      = 5.0
KM_PER_DEG_LAT    = 111.0
LAST_SEEN_CUTOFF  = 7  # days — ignore aircraft not seen recently


def haversine(lon1, lat1, lon2, lat2):
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    dlon, dlat = lon2 - lon1, lat2 - lat1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    return 6371 * 2 * asin(sqrt(a))


def load_speed_profiles(path='speed_profiles.json'):
    with open(path) as f:
        raw = json.load(f)
    # Convert to dict: model -> sorted list of (distance_km, median_speed_kph)
    profiles = {}
    for model, bins in raw.items():
        profiles[model] = sorted(
            [(b['distance_km'], b['median_speed_kph']) for b in bins],
            key=lambda x: x[0]
        )
    logger.info(f"Loaded speed profiles for: {list(profiles.keys())}")
    return profiles


def flight_time_minutes(distance_km, model_profile):
    """
    Integrate speed profile to get flight time in minutes.
    Returns None if distance exceeds reliable profile coverage.
    """
    if not model_profile:
        return None

    max_profile_dist = model_profile[-1][0]
    if distance_km > max_profile_dist:
        return None  # beyond reliable coverage for this model

    total_time_hours = 0.0
    remaining_km = distance_km

    for i, (bin_dist, bin_speed) in enumerate(model_profile):
        if remaining_km <= 0:
            break

        # Determine segment length
        next_dist = model_profile[i+1][0] if i+1 < len(model_profile) else bin_dist + 5
        segment_km = min(next_dist - bin_dist, remaining_km)

        if bin_speed > 0:
            total_time_hours += segment_km / bin_speed

        remaining_km -= segment_km

    return round(total_time_hours * 60, 1)


def get_mobilisable_aircraft(airfields, cutoff_days=LAST_SEEN_CUTOFF):
    """
    Return aircraft that are:
    - water bombers (payload_capacity_kg > 0)
    - last seen at an airfield (at_airfield=True)
    - seen within cutoff_days
    """
    cutoff_ts = int((datetime.now() - timedelta(days=cutoff_days)).timestamp())

    # Get latest telemetry per aircraft
    from sqlalchemy import func
    subq = db.query(
        migrate.FlightTelemetry.icao24,
        func.max(migrate.FlightTelemetry.timestamp).label('max_ts')
    ).group_by(
        migrate.FlightTelemetry.icao24
    ).subquery()

    latest = db.query(migrate.FlightTelemetry).join(
        subq,
        (migrate.FlightTelemetry.icao24 == subq.c.icao24) &
        (migrate.FlightTelemetry.timestamp == subq.c.max_ts)
    ).filter(
        migrate.FlightTelemetry.at_airfield == True,
        migrate.FlightTelemetry.timestamp >= cutoff_ts,
        migrate.FlightTelemetry.latest_airfield.isnot(None)
    ).all()

    # Filter to water bombers only
    water_bombers = db.query(
        migrate.TrackedAircraft.icao24,
        migrate.TrackedAircraft.aircraft_model
    ).filter(
        migrate.TrackedAircraft.payload_capacity_kg > 0,
        migrate.TrackedAircraft.aircraft_model.isnot(None)
    ).all()
    water_bomber_map = {ac.icao24: ac.aircraft_model for ac in water_bombers}

    mobilisable = []
    for rec in latest:
        if rec.icao24 not in water_bomber_map:
            continue
        if rec.latest_airfield not in airfields:
            continue
        model = water_bomber_map[rec.icao24]
        base_lat, base_lon, base_name  = airfields[rec.latest_airfield]
        mobilisable.append({
            'icao24':    rec.icao24,
            'model':     model,
            'airfield':  rec.latest_airfield,
            'base_lat':  base_lat,
            'base_lon':  base_lon,
            'base_name': base_name,
            'last_seen': rec.timestamp
        })

    logger.info(f"Found {len(mobilisable)} mobilisable aircraft across "
                f"{len(set(a['airfield'] for a in mobilisable))} airfields")
    return mobilisable


def compute_bounding_box(airfields_used, padding_km=50):
    """
    Bounding box covering all airfields hosting tracked aircraft,
    with padding so coverage extends meaningfully beyond each base.
    """
    lats = [lat for lat, lon in airfields_used]
    lons = [lon for lat, lon in airfields_used]

    pad_deg_lat = padding_km / KM_PER_DEG_LAT
    pad_deg_lon = padding_km / (KM_PER_DEG_LAT * cos(radians(sum(lats)/len(lats))))

    return (
        min(lats) - pad_deg_lat,
        max(lats) + pad_deg_lat,
        min(lons) - pad_deg_lon,
        max(lons) + pad_deg_lon,
    )


def build_grid(lat_min, lat_max, lon_min, lon_max):
    """Build list of (lat, lon) cell centers at GRID_SIZE_KM resolution."""
    mid_lat = (lat_min + lat_max) / 2
    deg_per_km_lat = 1.0 / KM_PER_DEG_LAT
    deg_per_km_lon = 1.0 / (KM_PER_DEG_LAT * cos(radians(mid_lat)))

    step_lat = GRID_SIZE_KM * deg_per_km_lat
    step_lon = GRID_SIZE_KM * deg_per_km_lon

    cells = []
    lat = lat_min
    while lat <= lat_max:
        lon = lon_min
        while lon <= lon_max:
            cells.append((round(lat, 5), round(lon, 5)))
            lon += step_lon
        lat += step_lat

    logger.info(f"Grid: {len(cells)} cells "
                f"({ceil((lat_max-lat_min)/step_lat)} rows x "
                f"{ceil((lon_max-lon_min)/step_lon)} cols)")
    return cells, step_lat, step_lon


def compute_heatmap(cells, mobilisable, speed_profiles):
    results = []
    total = len(cells)

    for idx, (cell_lat, cell_lon) in enumerate(cells):
        if idx % 500 == 0:
            logger.info(f"Computing cell {idx}/{total}...")

        best_time     = None
        best_airfield = None
        best_dist     = None
        best_model    = None

        for aircraft in mobilisable:
            model = aircraft['model']
            if model not in speed_profiles:
                continue

            dist = haversine(
                aircraft['base_lon'], aircraft['base_lat'],
                cell_lon, cell_lat
            )

            t = flight_time_minutes(dist, speed_profiles[model])
            if t is None:
                continue

            if best_time is None or t < best_time:
                best_time     = t
                best_airfield = aircraft['base_name'] 
                best_dist     = round(dist, 1)
                best_model    = aircraft['model']

        results.append((cell_lat, cell_lon, best_time, best_airfield, best_dist, best_model))

    covered = sum(1 for r in results if r[2] is not None)
    logger.info(f"Coverage: {covered}/{total} cells reachable ({100*covered//total}%)")
    return results


def to_geojson(results, step_lat, step_lon):
    """
    Convert heatmap results to a GeoJSON FeatureCollection.
    Each cell is a polygon with response_time_min property.
    """
    features = []
    half_lat = step_lat / 2
    half_lon = step_lon / 2

    for lat, lon, minutes in results:
        # Cell polygon corners
        coords = [[
            [lon - half_lon, lat - half_lat],
            [lon + half_lon, lat - half_lat],
            [lon + half_lon, lat + half_lat],
            [lon - half_lon, lat + half_lat],
            [lon - half_lon, lat - half_lat],
        ]]
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": coords
            },
            "properties": {
                "response_time_min": minutes,
                "lat": lat,
                "lon": lon
            }
        })

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "generated_at": datetime.now().isoformat(),
            "grid_size_km": GRID_SIZE_KM,
            "total_cells":  len(results),
            "covered_cells": sum(1 for _, _, t in results if t is not None)
        }
    }

def to_compact_grid(results, step_lat, step_lon, lat_min, lon_min):
    lats = sorted(set(r[0] for r in results))
    lons = sorted(set(r[1] for r in results))
    rows = len(lats)
    cols = len(lons)

    cell_lookup = {(r[0], r[1]): r for r in results}
    values    = []
    airfields = []
    distances = []
    models    = []

    for lat in sorted(lats, reverse=True):
        for lon in sorted(lons):

            entry = cell_lookup.get((lat, lon))
            models.append(entry[5] if entry else None)

            r = cell_lookup.get((lat, lon))
            if r and r[2] is not None:
                values.append(round(r[2], 1))
                airfields.append(r[3])
                distances.append(r[4])
            else:
                values.append(None)
                airfields.append(None)
                distances.append(None)

    covered = sum(1 for v in values if v is not None)

    return {
        "metadata": {
            "generated_at":  datetime.now().isoformat(),
            "grid_size_km":  GRID_SIZE_KM,
            "lat_min":       round(min(lats), 5),
            "lat_max":       round(max(lats), 5),
            "lon_min":       round(min(lons), 5),
            "lon_max":       round(max(lons), 5),
            "step_lat":      round(step_lat, 6),
            "step_lon":      round(step_lon, 6),
            "rows":          rows,
            "cols":          cols,
            "total_cells":   len(values),
            "covered_cells": covered,
        },
        "values":    values,
        "airfields": airfields,
        "distances": distances,
        "models": models 
    }

def parse_fleet_arg(fleet_str):
    """
    Parse fleet string: "CL2T:LFTW:3,AT8T:LFML:2"
    Returns list of dicts: [{model, airfield_icao, count}]
    """
    if not fleet_str:
        return []
    
    fleet = []
    for entry in fleet_str.split(','):
        parts = entry.strip().split(':')
        if len(parts) != 3:
            raise ValueError(f"Invalid fleet entry '{entry}' — expected MODEL:AIRFIELD:COUNT")
        model, airfield, count = parts
        fleet.append({
            'model':         model.strip().upper(),
            'airfield_icao': airfield.strip().upper(),
            'count':         int(count.strip())
        })
    return fleet


def load_predetermined_fleet(fleet_entries, airfields_dict, speed_profiles):
    """
    Build aircraft list from CLI fleet spec.
    airfields_dict: {icao: (lat, lon, name)}
    speed_profiles: {model: [...]}
    Returns list in same format as load_mobilisable_aircraft()
    """
    aircraft = []
    for entry in fleet_entries:
        model         = entry['model']
        airfield_icao = entry['airfield_icao']
        count         = entry['count']

        if airfield_icao not in airfields_dict:
            logger.warning(f"Airfield {airfield_icao} not found in DB — skipping")
            continue

        if model not in speed_profiles:
            logger.warning(f"No speed profile for model {model} — skipping")
            continue

        lat, lon, name = airfields_dict[airfield_icao]

        for i in range(count):
            aircraft.append((
                f"scenario_{model}_{airfield_icao}_{i}",  # fake icao24
                lat, lon,
                name,
                model
            ))

    logger.info(f"Predetermined fleet: {len(aircraft)} aircraft from {len(fleet_entries)} entries")
    return aircraft


if __name__ == "__main__":
    LOG_FORMAT = "%(asctime)s [%(levelname)s] [%(filename)s:%(lineno)d] %(message)s"
    logging.basicConfig(
        level=logging.INFO, format=LOG_FORMAT,
        datefmt="%H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)]
    )

    parser = argparse.ArgumentParser(description="Generate response time heatmap")
    parser.add_argument('--profiles',   default='speed_profiles.json')
    parser.add_argument('--output',     default='heatmap.geojson')
    parser.add_argument('--padding',    type=int, default=50,
                        help='Padding beyond airfields in km (default: 50)')
    parser.add_argument('--cutoff',     type=int, default=LAST_SEEN_CUTOFF,
                        help='Days since last seen to consider aircraft active')
    parser.add_argument('--fleet',      type=str, default=None,
                        help='Predetermined fleet: MODEL:AIRFIELD:COUNT,... e.g. CL2T:LFTW:3,AT8T:LFML:2')
    parser.add_argument('--supplement', action='store_true',
                        help='Add predetermined fleet on top of real fleet (default: replace)')
    parser.add_argument('--name', type=str, default=None,
                    help='Name for this heatmap scenario (default: auto-generated)')
    args = parser.parse_args()

    # 1. Load speed profiles
    speed_profiles = load_speed_profiles(args.profiles)

    # 2. Load airfields
    airfields_all = db.query(migrate.Airfield).all()
    airfields = {af.icao: (af.lat, af.lon, af.name) for af in airfields_all}

    # 3. Build mobilisable aircraft list
    if args.fleet:
        # Parse fleet string
        predetermined = []
        for entry in args.fleet.split(','):
            parts = entry.strip().split(':')
            if len(parts) != 3:
                logger.error(f"Invalid fleet entry '{entry}' — expected MODEL:AIRFIELD:COUNT")
                sys.exit(1)
            model, airfield_icao, count = parts[0].strip(), parts[1].strip().upper(), int(parts[2].strip())

            if airfield_icao not in airfields:
                logger.error(f"Airfield {airfield_icao} not found in DB")
                sys.exit(1)
            if model not in speed_profiles:
                logger.warning(f"No speed profile for model '{model}' — skipping")
                continue

            lat, lon, name = airfields[airfield_icao]
            for i in range(count):
                predetermined.append({
                    'icao24':   f"scenario_{model}_{airfield_icao}_{i}",
                    'model':    model,
                    'base_lat': lat,
                    'base_lon': lon,
                    'base_name': name,
                })
        logger.info(f"Predetermined fleet: {len(predetermined)} aircraft")

        if args.supplement:
            real_fleet  = get_mobilisable_aircraft(airfields, cutoff_days=args.cutoff)
            mobilisable = real_fleet + predetermined
            logger.info(f"Supplemented: {len(real_fleet)} real + {len(predetermined)} scenario = {len(mobilisable)} total")
        else:
            mobilisable = predetermined
    else:
        mobilisable = get_mobilisable_aircraft(airfields, cutoff_days=args.cutoff)

    if not mobilisable:
        logger.error("No mobilisable aircraft found — check fleet or last_seen cutoff")
        sys.exit(1)

    # 4. Bounding box from active airfields only
    active_airfield_coords = list({
        (a['base_lat'], a['base_lon'])
        for a in mobilisable
    })
    lat_min, lat_max, lon_min, lon_max = compute_bounding_box(
        active_airfield_coords, padding_km=args.padding
    )
    logger.info(f"Bounding box: lat [{lat_min:.3f}, {lat_max:.3f}] "
                f"lon [{lon_min:.3f}, {lon_max:.3f}]")

    # 5. Build grid
    cells, step_lat, step_lon = build_grid(lat_min, lat_max, lon_min, lon_max)

    # 6. Compute heatmap
    results = compute_heatmap(cells, mobilisable, speed_profiles)

    # 7. Export
    grid = to_compact_grid(results, step_lat, step_lon, lat_min, lon_min)

    if args.name:
        scenario_name = args.name.replace(' ', '_')
    else:
        scenario_name = 'realfleet' if not args.fleet else 'scenario_' + args.fleet.replace(',', '_').replace(':', '-')

    output_path = os.path.join(
        os.getenv("HEATMAP_DIR", "."),
        f"heatmap_{scenario_name}.json"
    )

    with open(output_path, 'w') as f:
        json.dump(grid, f, separators=(',', ':'))
        logger.info(f"Heatmap saved — {grid['metadata']['rows']} rows x "
                    f"{grid['metadata']['cols']} cols = "
                    f"{grid['metadata']['total_cells']} cells")
    logger.info(f"Heatmap saved to {output_path}")