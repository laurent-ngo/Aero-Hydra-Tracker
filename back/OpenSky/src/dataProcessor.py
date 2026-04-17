import os
import time
import json
import argparse
import requests
import sys
import logging
logger = logging.getLogger(__name__)

from datetime import datetime, timedelta
import math
from datetime import datetime
from sqlalchemy import create_engine, desc, func, or_, and_
from sqlalchemy.orm import sessionmaker
from math import radians, cos, sin, asin, sqrt
from collections import Counter
import numpy as np
from sklearn.cluster import DBSCAN
from scipy.spatial import ConvexHull
from shapely.geometry import Polygon, MultiPolygon, MultiPoint, Point
from shapely.ops import unary_union
from elevation import ElevationProvider

import migrate
from dataCollector import orchestrate_sync, update_adsb_cache, discover_new_aircraft

user = os.getenv('DB_USER', 'neondb_owner')
password = os.getenv('DB_PASSWORD')
db_host = os.getenv('DB_HOST')
db_name = os.getenv('DB_NAME', 'neondb')
db_opts = os.getenv('DB_OPTIONS', 'sslmode=disable')

db_url = f"postgresql://{user}:{password}@{db_host}/{db_name}?{db_opts}"

# --- Database Setup ---
engine = create_engine(db_url)
Session = sessionmaker(bind=engine)
db = Session()

''' 
    Haversine: 
    formula calculates the shortest distance (great-circle distance) 
    between two points on a sphere, like Earth.
'''
def haversine(lon1, lat1, lon2, lat2):
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    dlon, dlat = lon2 - lon1, lat2 - lat1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    return 6371 * 2 * asin(sqrt(a))

def backfill_telemetry( icao_list = None):
    # 1. Get all unique ICAO24s that have empty speed data

    if icao_list == None:
        logger.info("No aircraft data")
        return
    aircraft_ids = db.query(migrate.FlightTelemetry.icao24).filter(
        migrate.FlightTelemetry.icao24.in_(icao_list),
        migrate.FlightTelemetry.speed_kph == None
    ).distinct().all()
 

    for (icao,) in aircraft_ids:
        logger.debug(f"Processing aircraft: {icao}")
        
        # 2. Get all points for this aircraft, oldest first
        points = db.query(migrate.FlightTelemetry).filter(
            migrate.FlightTelemetry.icao24 == icao
        ).order_by(migrate.FlightTelemetry.timestamp.asc()).all()

        for i in range(1, len(points)):
            curr = points[i]
            prev = points[i-1]

            time_diff = curr.timestamp - prev.timestamp

            # 3. Logic: 
            if  curr.speed_kph is None:
                
                hours = time_diff / 3600
                minutes = time_diff / 60

                # Horizontal Speed
                dist_km = haversine(prev.lon, prev.lat, curr.lon, curr.lat)
                curr.speed_kph = round(dist_km / hours, 2)
                curr.speed_kt = round(curr.speed_kph * 0.539957, 2)

                # Vertical Speed
                if curr.baro_altitude is not None and prev.baro_altitude is not None:
                    alt_diff_m = curr.baro_altitude - prev.baro_altitude
                    curr.vertical_speed_mmin = round(alt_diff_m / minutes, 2)
                    curr.vertical_speed_ftmin = round(curr.vertical_speed_mmin * 3.28084, 0)
        
        # Commit per aircraft to keep memory usage low
        db.commit()
    logger.info("Backfill complete!")
    
def backfill_agl():
    # 1. Fetch only records that have baro_altitude but missing AGL
    points_to_fix = db.query(migrate.FlightTelemetry).filter(
        migrate.FlightTelemetry.baro_altitude != None,
        migrate.FlightTelemetry.altitude_agl_ft == None
    ).order_by(
        desc(migrate.FlightTelemetry.timestamp)
    ).all() # Processing 200 at a time is safer

    if not points_to_fix:
        logger.debug("No pending AGL calculations found.")
        return

    logger.info(f"Calculating AGL for {len(points_to_fix)} points...")
   
    elevation_providers = [
        ElevationProvider("../data/azur.tif"),
        ElevationProvider("../data/france.tif"),
        ElevationProvider("../data/italy.tif"),
        ElevationProvider("../data/sicilia.tif"),
        ElevationProvider("../data/catalogna.tif"),
        ElevationProvider("../data/spain.tif"),
        ElevationProvider("../data/corsica.tif"),
        ElevationProvider("../data/switzerland.tif"),
        ElevationProvider("../data/portugal.tif"),
        ElevationProvider("../data/brittany.tif"),
        ElevationProvider("../data/belgium.tif"),
        ElevationProvider("../data/germany.tif"),
        ElevationProvider("../data/sweden.tif"),
    ]
    
    ELEVATION_BBOX = {
        'lamin': 35.9,
        'lamax': 60.6,
        'lomin': -9.6,
        'lomax': 20,
    }

    for p in points_to_fix:
        if not (ELEVATION_BBOX['lamin'] <= p.lat <= ELEVATION_BBOX['lamax'] and
            ELEVATION_BBOX['lomin'] <= p.lon <= ELEVATION_BBOX['lomax']):
            p.altitude_agl_ft = 60000
        else:
            ground_m = 0
            for provider in elevation_providers:
                ground_m = provider.get_elevation(p.lat, p.lon)
                if ground_m is not None:
                    break
            
            if ground_m is not None:
                # 3. Calculation: MSL - Ground = AGL
                agl_m = max(0, p.baro_altitude - ground_m)
                p.altitude_agl_ft = round(agl_m * 3.28084, 0)
            else:
                p.altitude_agl_ft = round(p.baro_altitude * 3.28084, 0)

    db.commit()
    logger.info("Batch AGL backfill complete.")
    
def calculate_distance(lat1, lon1, lat2, lon2):
    """Returns distance in km between two points."""
    R = 6371.0  # Earth radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def get_unprocessed_points():
    points = db.query(migrate.FlightTelemetry).filter(
        migrate.FlightTelemetry.is_processed == False,
        or_(
            and_(  
                migrate.FlightTelemetry.altitude_agl_ft != None,
                migrate.FlightTelemetry.baro_altitude_ft != None,
                migrate.FlightTelemetry.altitude_agl_ft < 60000
            ),
            migrate.FlightTelemetry.on_ground == True
        ) 
    ).order_by(
        migrate.FlightTelemetry.timestamp,
        desc(migrate.FlightTelemetry.timestamp)
    ).all()
  
    return points
    
def get_lastest_aircraft_data():
    last_known_airfields = db.query(
        migrate.FlightTelemetry.icao24,
        migrate.FlightTelemetry.latest_airfield,
        migrate.FlightTelemetry.latest_waterfield,
        migrate.FlightTelemetry.is_full,
        migrate.FlightTelemetry.timestamp
    ).filter(
        migrate.FlightTelemetry.latest_airfield.isnot(None)
    ).distinct(
        migrate.FlightTelemetry.icao24
    ).order_by(
        migrate.FlightTelemetry.icao24, 
        desc(migrate.FlightTelemetry.timestamp)
    ).all()
    
    airfield_dict   = {row.icao24: row.latest_airfield   for row in last_known_airfields}
    is_full_dict    = {row.icao24: row.is_full            for row in last_known_airfields}
    waterfield_dict = {row.icao24: row.latest_waterfield  for row in last_known_airfields}

    return airfield_dict, is_full_dict, waterfield_dict

def get_water_bombers():
    water_bombers = db.query(
        migrate.TrackedAircraft.icao24,
        migrate.TrackedAircraft.payload_capacity_kg,
        migrate.TrackedAircraft.last_seen
    ).filter(
        migrate.TrackedAircraft.payload_capacity_kg> 0
    ).distinct(
        migrate.TrackedAircraft.icao24
    ).all()
    
    water_bombers_dict = {row.icao24: row.payload_capacity_kg for row in water_bombers}

    return water_bombers_dict

def get_level_poly(level=3):
    roi_data = db.query(migrate.RegionOfInterest).filter(migrate.RegionOfInterest.level == level).all()
    level_polygons = []
    for r in roi_data:
        try:
            poly = Polygon(json.loads(r.geometry))
            level_polygons.append(poly)
        except(TypeError, ValueError) as e:
            logger.error(f"Skipping ROI {r.id} due to invalid geometry: {e}")
            continue

    return level_polygons

def proximity_check( point, airfields, radius_km, alt_threshold_ft):
    for af in airfields:
        dist = calculate_distance(point.lat, point.lon, af.lat, af.lon)

        if dist <= radius_km and ( point.on_ground or point.altitude_agl_ft <= alt_threshold_ft ) :
            return af
    return None

def label_flight_phases(threshold_ft=750, water_threshold_ft=10, airfield_radius=8.0, airfield_alt_threshold=1500, waterfield_alt_threshold=200):
    # 1. Load all airfields into memory for fast lookup
    airfields = db.query(migrate.Airfield).all()

    water_rois = db.query(migrate.RegionOfInterest).filter(
        migrate.RegionOfInterest.type == 'water',
        migrate.RegionOfInterest.level == 2,
        migrate.RegionOfInterest.water_location_id.isnot(None)
    ).all()
    
    water_roi_polys = []
    for roi in water_rois:
        try:
            coords = json.loads(roi.geometry)
            if len(coords) >= 3:
                poly = Polygon(coords)
                wl = db.query(migrate.WaterLocation).filter_by(id=roi.water_location_id).first()
                if wl:
                    water_roi_polys.append((poly, wl.ref))
        except Exception:
            continue

    points = get_unprocessed_points()
    if not points:
        logger.debug("No new points to label.")
        return
    
    airfield_dict, is_full_dict, waterfield_dict  = get_lastest_aircraft_data()
    water_bombers_dict = get_water_bombers()

    count_low_pass = 0
    count_over_water = 0
    count_at_airfield = 0
    count_at_waterfield = 0

    # Runs throught every new points
    for p in points:

        p.at_airfield = False
        p.is_over_water = False
        p.is_low_pass = False

        p.is_full = is_full_dict.get(p.icao24)
        if p.is_full is None:
            p.is_full =  p.icao24 in water_bombers_dict
     
        # 1. Proximity Check (Highest priority)
        nearby_af = proximity_check(p, airfields, airfield_radius, airfield_alt_threshold)
    
        if nearby_af:
            p.at_airfield = True
            p.latest_airfield = nearby_af.icao
            airfield_dict[p.icao24] = nearby_af.icao
            p.latest_waterfield = None
            p.is_full = True if p.icao24 in water_bombers_dict else False
            count_at_airfield += 1

        # 2. Inheritance Logic (If not currently at an airfield)
        else:
            # Check if we already found an airfield for this plane in this batch
            if p.icao24 in airfield_dict:
                p.latest_airfield = airfield_dict[p.icao24]
            else:
                p.latest_airfield = None
        
            # 3. Label Phase (Only if NOT at an airfield)
            if p.baro_altitude_ft is not None and p.altitude_agl_ft is not None and abs(p.baro_altitude_ft - p.altitude_agl_ft) < water_threshold_ft:
                p.is_over_water = True
                count_over_water += 1

            if p.altitude_agl_ft is not None and p.altitude_agl_ft <= threshold_ft:
                p.is_low_pass = True
                count_low_pass += 1
                p.is_full = False

            # Waterfield check — seaplane inside a linked water ROI below threshold
            p.latest_waterfield = waterfield_dict.get(p.icao24)  # inherit by default

            is_seaplane = db.query(migrate.TrackedAircraft).filter_by(icao24=p.icao24).first()
            if is_seaplane and is_seaplane.sea_landing and p.altitude_agl_ft is not None and p.altitude_agl_ft <= waterfield_alt_threshold:
                pt = Point(p.lat, p.lon)  # [lat,lon] space
                for poly, ref in water_roi_polys:
                    if poly.contains(pt):
                        p.latest_waterfield = ref
                        waterfield_dict[p.icao24] = ref
                        count_at_waterfield += 1
                        break
            else:
                p.latest_waterfield = waterfield_dict.get(p.icao24)

        p.is_processed = True

    db.commit()
    logger.debug(
        f"Labeling complete: {count_low_pass} Low Pass, {count_over_water} Over Water, "
        f"{count_at_airfield} near Airfields, {count_at_waterfield} near Waterfields."
    )

def detect_regions_of_interest_clustered(min_samples=5, distance_meters=200, type='fire'):
    cutoff_timestamp = int((datetime.now() - timedelta(days=90)).timestamp())

    if type == 'fire':
        points = (
            db.query(migrate.FlightTelemetry)
                .join(migrate.TrackedAircraft, migrate.FlightTelemetry.icao24 == migrate.TrackedAircraft.icao24)
                .filter(
                    migrate.FlightTelemetry.is_low_pass == True,
                    migrate.FlightTelemetry.timestamp >= cutoff_timestamp,
                    migrate.TrackedAircraft.payload_capacity_kg > 0,
                    migrate.TrackedAircraft.aircraft_type == "airplane",
                    migrate.FlightTelemetry.is_over_water == False
                ).all()
        )
    elif type == 'water':
        points = (
            db.query(migrate.FlightTelemetry)
                .join(migrate.TrackedAircraft, migrate.FlightTelemetry.icao24 == migrate.TrackedAircraft.icao24)
                .filter(
                    migrate.FlightTelemetry.is_over_water == True,
                    migrate.FlightTelemetry.timestamp >= cutoff_timestamp,
                    migrate.TrackedAircraft.payload_capacity_kg > 0,
                    migrate.TrackedAircraft.sea_landing == True,
                    migrate.TrackedAircraft.aircraft_type == "airplane",
                ).all()
        )
    else:
        logger.error(f"incorrect value in argument 'type': {type}")
        return

    if len(points) < min_samples:
        logger.debug(f"Not enough points to cluster ({type}).")
        return

    # ── Cluster ──────────────────────────────────────────────
    coords = np.array([[p.lat, p.lon] for p in points])
    kms_per_radian = 6371.0088
    epsilon = (distance_meters / 1000) / kms_per_radian

    dbscan = DBSCAN(
        eps=epsilon, min_samples=min_samples,
        algorithm='ball_tree', metric='haversine'
    ).fit(np.radians(coords))
    labels       = dbscan.labels_
    unique_labels = set(labels) - {-1}

    if not unique_labels:
        logger.debug(f"No clusters found ({type}).")
        return

    # ── Build one canonical polygon per cluster ───────────────
    # These are derived purely from telemetry — same data = same polygons
    cluster_polygons = {}
    for k in unique_labels:
        cluster_points = coords[labels == k]
        if len(cluster_points) < 3:
            continue
        cluster_polygons[k] = MultiPoint(cluster_points).convex_hull

    # ── Load existing level-1 ROIs of this type ───────────────
    existing_rois = db.query(migrate.RegionOfInterest).filter(
        migrate.RegionOfInterest.level == 1,
        migrate.RegionOfInterest.type == type
    ).all()

    # Index existing ROIs by their geometry centroid for spatial matching
    # (same approach as grow_and_level_up_rois)
    matched_existing_ids = set()

    for k, new_poly in cluster_polygons.items():
        cluster_points = coords[labels == k]
        new_centroid   = new_poly.centroid   # x=lat, y=lon in [lat,lon] space

        # Try to find an existing ROI whose stored geometry overlaps this cluster
        matched_roi = None
        for roi in existing_rois:
            if roi.id in matched_existing_ids:
                continue
            try:
                existing_coords = json.loads(roi.geometry)
                if len(existing_coords) < 3:
                    continue
                existing_poly = Polygon(existing_coords)
                # Match if centroids are close OR polygons intersect
                if new_poly.intersects(existing_poly):
                    matched_roi = roi
                    break
            except Exception:
                continue

        hull_coords = list(new_poly.exterior.coords)

        if matched_roi:
            # ✅ Reuse — overwrite with freshly computed geometry (idempotent)
            matched_existing_ids.add(matched_roi.id)
            matched_roi.lat         = new_centroid.x   # x=lat in [lat,lon] space
            matched_roi.lon         = new_centroid.y   # y=lon
            matched_roi.geometry    = json.dumps(hull_coords)
            matched_roi.density     = len(cluster_points)
            matched_roi.detected_at = datetime.now()
            # preserve name and type
        else:
            # 🆕 New cluster not seen before
            new_roi = migrate.RegionOfInterest(
                lat=new_centroid.x,
                lon=new_centroid.y,
                geometry=json.dumps(hull_coords),
                density=len(cluster_points),
                name=f"Area {datetime.now().strftime('%H%M%S')}",
                detected_at=datetime.now(),
                level=1,
                type=type
            )
            db.add(new_roi)

    # ── Remove stale ROIs no longer supported by any cluster ──
    stale = [roi for roi in existing_rois if roi.id not in matched_existing_ids]
    for roi in stale:
        db.delete(roi)

    db.commit()

def grow_and_level_up_rois(starting_level=1, buffer_km=1.0, type='fire'):
    rois = db.query(migrate.RegionOfInterest).filter(
        migrate.RegionOfInterest.level == starting_level,
        migrate.RegionOfInterest.type == type
    ).all()
    if not rois:
        logger.debug(f"No {type} ROIs found at Level {starting_level} to grow.")
        return

    # Fetch water landing locations for linking (water type only)
    water_locations = []
    if type == 'water':
        water_locations = db.query(migrate.WaterLocation).all()

    polygons = []
    for roi in rois:
        coords = json.loads(roi.geometry)
        if len(coords) >= 3:
            buffer_deg = buffer_km / 111.0
            poly = Polygon(coords).buffer(buffer_deg)
            polygons.append(poly)
    if not polygons:
        return

    merged_geometry = unary_union(polygons)
    final_shapes = (
        [merged_geometry]
        if isinstance(merged_geometry, Polygon)
        else list(merged_geometry.geoms)
    )
    new_level = starting_level + 1

    existing_rois = db.query(migrate.RegionOfInterest).filter(
        migrate.RegionOfInterest.level == new_level,
        migrate.RegionOfInterest.type.in_([type, 'training'])
    ).all()

    for roi in existing_rois:
        if roi.type == 'training':
            roi.type = type
    db.flush()

    existing_parsed = []
    for roi in existing_rois:
        try:
            coords = json.loads(roi.geometry)
            if len(coords) >= 3:
                existing_parsed.append((roi, Polygon(coords)))
        except Exception:
            pass

    # Build overlap scores for greedy matching
    overlap_scores = []
    for i, shape in enumerate(final_shapes):
        for roi, roi_poly in existing_parsed:
            try:
                if shape.intersects(roi_poly):
                    area = shape.intersection(roi_poly).area
                    overlap_scores.append((area, i, roi, roi_poly))
            except Exception:
                continue

    overlap_scores.sort(key=lambda x: x[0], reverse=True)
    matched_shape_indices = set()
    matched_existing_ids  = set()
    shape_to_roi          = {}

    for area, i, roi, roi_poly in overlap_scores:
        if i in matched_shape_indices or roi.id in matched_existing_ids:
            continue
        shape_to_roi[i] = roi
        matched_shape_indices.add(i)
        matched_existing_ids.add(roi.id)

    for i, shape in enumerate(final_shapes):
        merged_coords = list(shape.exterior.coords)
        centroid_lat  = shape.centroid.x
        centroid_lon  = shape.centroid.y

        # Check if any water location falls inside this shape
        water_location_id = None
        roi_name          = f"Level {new_level} Zone - Area {i + 1}"
        if type == 'water':
            for wl in water_locations:
                if shape.contains(Point(wl.lat, wl.lon)):  # [lat,lon] space
                    water_location_id = wl.id
                    roi_name          = wl.name
                    logger.debug(f"Level {new_level} water ROI linked to: {wl.name} (id={wl.id})")
                    break

        if i in shape_to_roi:
            roi = shape_to_roi[i]
            roi.lat              = centroid_lat
            roi.lon              = centroid_lon
            roi.geometry         = json.dumps(merged_coords)
            roi.density          = 0
            roi.level            = new_level
            roi.name             = roi_name
            roi.detected_at      = datetime.now()
            roi.type             = type
            roi.water_location_id = water_location_id
        else:
            new_roi = migrate.RegionOfInterest(
                lat=centroid_lat,
                lon=centroid_lon,
                geometry=json.dumps(merged_coords),
                density=0,
                level=new_level,
                name=roi_name,
                detected_at=datetime.now(),
                type=type,
                water_location_id=water_location_id
            )
            db.add(new_roi)

    stale_rois = [roi for roi, _ in existing_parsed if roi.id not in matched_existing_ids]
    for roi in stale_rois:
        db.delete(roi)

    db.commit()
    logger.info(
        f"Success: Level {starting_level} → {len(final_shapes)} Level {new_level} "
        f"{type} ROIs (updated: {len(matched_shape_indices)}, "
        f"created: {len(final_shapes) - len(matched_shape_indices)}, "
        f"removed: {len(stale_rois)})."
    )

def sync_aircraft_metadata():
    logger.info("Promoting latest telemetry metadata to aircraft table...")
    
    # Get the latest point for every aircraft
    # This query finds the maximum ID for each ICAO24
    subquery = db.query(
        migrate.FlightTelemetry.icao24,
        func.max(migrate.FlightTelemetry.timestamp).label("max_ts")
    ).filter(
        migrate.FlightTelemetry.is_processed == True
    ).group_by(
        migrate.FlightTelemetry.icao24
    ).subquery()

    latest_points = db.query(migrate.FlightTelemetry).join(
        subquery,
        (migrate.FlightTelemetry.icao24 == subquery.c.icao24) &
        (migrate.FlightTelemetry.timestamp == subquery.c.max_ts)
    ).all()

    sync_count = 0
    for p in latest_points:
        # 2. Update the corresponding aircraft record
        ac_record = db.query(migrate.TrackedAircraft).filter(
            migrate.TrackedAircraft.icao24 == p.icao24
        ).first()
        
        if ac_record:
            ac_record.last_seen = p.timestamp
            sync_count += 1

    db.commit()
    logger.info(f"Sync complete: {sync_count} aircraft updated with their latest status.")

if __name__ == "__main__":

    log_level_name = os.getenv('LOG_LEVEL', 'INFO').upper()
    log_level = getattr(logging, log_level_name, logging.INFO)

    LOG_FORMAT = "%(asctime)s [%(levelname)s] [%(filename)s:%(lineno)d] %(message)s"
    DATE_FORMAT = "%H:%M:%S"

    logging.basicConfig(
        level=log_level,
        format=LOG_FORMAT,
        datefmt=DATE_FORMAT,
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )

    parser = argparse.ArgumentParser(description="AERO-HYDRA data collector")

    parser.add_argument(
        "--active", 
        action="store_true", 
        help="Only active aircrafts"
    )

    parser.add_argument(
        "--AGL", 
        action="store_true", 
        help="Only set AGL altitude"
    )
    
    parser.add_argument(
        "--ROI", 
        action="store_true", 
        help="Only set ROIs"
    )

    parser.add_argument(
        "--adsb-cache",
        action="store_true",
        help="Only update ADSB supplement cache (fast, no OpenSky call)"
    )

    parser.add_argument(
        "--discover",
        action="store_true",
        help="Scan for new firefighting aircraft not yet in the DB"
    )

    args = parser.parse_args()

    if args.adsb_cache:
        update_adsb_cache()
        sys.exit(0)

    
    if args.ROI: 

        detect_regions_of_interest_clustered(type='fire')
        detect_regions_of_interest_clustered(type='water')

        grow_and_level_up_rois(starting_level=1, buffer_km=1.0, type='fire')
        
        grow_and_level_up_rois(starting_level=1, buffer_km=1.0, type='water')

        sys.exit(0)

    # In the main block:
    if args.discover:
        findings = discover_new_aircraft()
        if findings:
            print(f"\n{'ICAO24':8} | {'REG':10} | {'MODEL':40} | {'FLIGHT':10} | POSITION")
            print('-' * 90)
            for ac in findings:
                print(f"{ac['icao24']:8} | {ac['reg']:10} | {ac['model']:40} | {ac['flight']:10} | {ac['lat']},{ac['lon']}")
            print(f"\n{len(findings)} new aircraft found.")
        else:
            print("No new aircraft found.")
        sys.exit(0)

    icao_list = orchestrate_sync()


    if args.AGL:
        backfill_agl()
        label_flight_phases()
    else:
        if len(icao_list) > 0:

            backfill_telemetry(icao_list)
            backfill_agl()
            label_flight_phases()
            sync_aircraft_metadata()

        
