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
from sqlalchemy import create_engine, desc
from sqlalchemy.orm import sessionmaker
from math import radians, cos, sin, asin, sqrt
from collections import Counter
import numpy as np
from sklearn.cluster import DBSCAN
from scipy.spatial import ConvexHull
from shapely.geometry import Polygon, MultiPolygon, MultiPoint, Point
from shapely.ops import unary_union
import elevation

import migrate

user = os.getenv('DB_USER', 'neondb_owner')
password = os.getenv('DB_PASSWORD')
db_host = os.getenv('DB_HOST')
db_name = os.getenv('DB_NAME', 'neondb')
db_opts = os.getenv('DB_OPTIONS', 'sslmode=require')

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

def backfill_telemetry():
    # 1. Get all unique ICAO24s that have empty speed data
    aircraft_ids = db.query(migrate.FlightTelemetry.icao24).filter(
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
    # We process in batches to be gentle on the API and memory
    points_to_fix = db.query(migrate.FlightTelemetry).filter(
        migrate.FlightTelemetry.baro_altitude != None,
        migrate.FlightTelemetry.altitude_agl_ft == None
    ).all() # Processing 500 at a time is safer

    if not points_to_fix:
        logger.debug("No pending AGL calculations found.")
        return

    logger.info(f"Calculating AGL for {len(points_to_fix)} points...")

    for p in points_to_fix:
        # 2. Get the ground height from your new method
        ground_m = elevation.get_or_fetch_elevation(p.lat, p.lon)
        
        if ground_m is not None:
            # 3. Calculation: MSL - Ground = AGL
            agl_m = p.baro_altitude - ground_m
            p.altitude_agl_ft = round(agl_m * 3.28084, 0)

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
        migrate.FlightTelemetry.altitude_agl_ft != None,
        migrate.FlightTelemetry.baro_altitude_ft != None,
        migrate.FlightTelemetry.is_processed == False 
    ).order_by(
        migrate.FlightTelemetry.timestamp,
        desc(migrate.FlightTelemetry.timestamp)
    ).all()
  
    return points
    
def get_lastest_aircraft_data():
    last_known_airfields = db.query(
        migrate.FlightTelemetry.icao24,
        migrate.FlightTelemetry.latest_airfield,
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
    
    airfield_dict = {row.icao24: row.latest_airfield for row in last_known_airfields}
    is_full_dict = {row.icao24: row.is_full for row in last_known_airfields}

    return airfield_dict, is_full_dict

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

        if dist <= radius_km and point.altitude_agl_ft <= alt_threshold_ft:
            return af
    return None

def label_flight_phases(threshold_ft=950, water_threshold_ft=2, airfield_radius=8.0, airfield_alt_threshold=1500):
    # 1. Load all airfields into memory for fast lookup
    airfields = db.query(migrate.Airfield).all()

    level_3_polygons = get_level_poly()
    
    points = get_unprocessed_points()
    if not points:
        logger.debug("No new points to label.")
        return
    
    
    airfield_dict, is_full_dict = get_lastest_aircraft_data()   
    water_bombers_dict = get_water_bombers()

    count_low_pass = 0
    count_over_water = 0 
    count_at_airfield = 0

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
            
            # Update cache and state
            airfield_dict[p.icao24] = nearby_af.icao
            p.is_full = True
            
            count_at_airfield += 1

        # 2. Inheritance Logic (If not currently at an airfield)
        else:
            # Check if we already found an airfield for this plane in this batch
            if p.icao24 in airfield_dict:
                p.latest_airfield = airfield_dict[p.icao24]
            else:
                p.latest_airfield = None
        
            # 3. Label Phase (Only if NOT at an airfield)
            if (p.baro_altitude_ft - p.altitude_agl_ft) < water_threshold_ft:
                p.is_over_water = True
                count_over_water += 1

            if p.altitude_agl_ft <= threshold_ft:
                p.is_low_pass = True
                count_low_pass += 1

                if p.is_full:
                    point_geom = Point(p.lat, p.lon)
                    for poly in level_3_polygons:
                        if poly.contains(point_geom):
                            p.is_full = False
                            break
        
        p.is_processed = True

    db.commit()
    logger.debug(f"Labeling complete: {count_low_pass} Low Pass, {count_over_water} Over Water, {count_at_airfield} near Airfields.")

def detect_regions_of_interest_clustered(min_samples=5, distance_meters=200, type='fire'):
    # 1. Calculate the cutoff (5 days ago from now)
    cutoff_timestamp = int((datetime.now() - timedelta(days=5)).timestamp())

    # 1. Fetch points
    if type == 'fire':
        points = (
            db.query(migrate.FlightTelemetry)
                .join(migrate.TrackedAircraft, migrate.FlightTelemetry.icao24 == migrate.TrackedAircraft.icao24)
                .filter(
                    migrate.FlightTelemetry.is_low_pass == True,
                    migrate.FlightTelemetry.timestamp >= cutoff_timestamp,   
                    migrate.TrackedAircraft.payload_capacity_kg > 0   
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
                    migrate.TrackedAircraft.sea_landing == True
                ).all()
            )


    if len(points) < min_samples:
        logger.debug(f"Not enough points to cluster ({type}).")
        return

    # 2. Prepare data for DBSCAN (Coordinates in radians for Haversine distance)
    coords = np.array([[p.lat, p.lon] for p in points])
    kms_per_radian = 6371.0088
    epsilon = (distance_meters / 1000) / kms_per_radian

    # 3. Perform Clustering
    dbscan = DBSCAN(eps=epsilon, min_samples=min_samples, algorithm='ball_tree', metric='haversine').fit(np.radians(coords))
    labels = dbscan.labels_
    unique_labels = set(labels) - {-1}
    
    # Fetch existing ROIs from DB to compare
    existing_rois = db.query(migrate.RegionOfInterest).filter(migrate.RegionOfInterest.type == type).all()

    for k in unique_labels:
        cluster_points = coords[labels == k]
        if len(cluster_points) < 3: continue

        # Create the new cluster polygon
        new_poly = MultiPoint(cluster_points).convex_hull
        
        merged = False
        for old_roi in existing_rois:
            old_poly = Polygon(json.loads(old_roi.geometry))
            
            # Identify if new cluster intersects or is inside existing ROI
            if new_poly.intersects(old_poly):
                # MERGE the two geometries
                combined_poly = unary_union([old_poly, new_poly]).convex_hull
                
                # Update existing record
                old_roi.geometry = json.dumps(list(combined_poly.exterior.coords))
                old_roi.density += len(cluster_points)
                old_roi.detected_at = datetime.now()
                merged = True
                break
        
        if not merged:
            # Save as a brand new ROI if no intersection found
            hull_points = list(new_poly.exterior.coords)
            new_roi = migrate.RegionOfInterest(
                lat=np.mean(cluster_points[:, 0]),
                lon=np.mean(cluster_points[:, 1]),
                geometry=json.dumps(hull_points),
                density=len(cluster_points),
                name=f"Area {datetime.now().strftime('%H%M%S')}",
                detected_at=datetime.now(),
                level=1,
                type=type
            )
            db.add(new_roi)
    db.commit()

def grow_and_level_up_rois(starting_level=1, buffer_km=1.0, type='fire'):
    # 1. Fetch only ROIs at the specific starting level
    rois = db.query(migrate.RegionOfInterest).filter(
        migrate.RegionOfInterest.level == starting_level,
        migrate.RegionOfInterest.type == type
    ).all()

    if not rois:
        logger.debug(f"No {type} ROIs found at Level {starting_level} to grow.")
        return

    polygons = []
    for roi in rois:
        coords = json.loads(roi.geometry)
        if len(coords) >= 3:
            # Convert km to degrees (~111km per degree)
            buffer_deg = buffer_km / 111.0
            # Buffer (Grow) the polygon
            poly = Polygon(coords).buffer(buffer_deg)
            polygons.append(poly)

    if not polygons:
        return

    # 2. REGROUP: Merge all overlapping expanded polygons
    merged_geometry = unary_union(polygons)

    # 3. Handle the result (Single Polygon or MultiPolygon)
    if isinstance(merged_geometry, Polygon):
        final_shapes = [merged_geometry]
    else:
        final_shapes = list(merged_geometry.geoms)

    
    # 4. SAVE the new higher-level ROIs
    new_level = starting_level + 1
    db.query(migrate.RegionOfInterest).filter(
        migrate.RegionOfInterest.level == new_level
    ).delete()
    for i, shape in enumerate(final_shapes):
        merged_coords = list(shape.exterior.coords)
        
        new_roi = migrate.RegionOfInterest(
            lat=shape.centroid.y,
            lon=shape.centroid.x,
            geometry=json.dumps(merged_coords),
            density=0, # New levels represent area, not raw points
            level=new_level,
            name=f"Level {new_level} Zone - Area {i+1}",
            detected_at=datetime.now(),
            type=type
        )
        db.add(new_roi)

    db.commit()
    logger.info(f"Success: Level {starting_level} expanded and merged into {len(final_shapes)} Level {new_level} {type} ROIs.")


def sync_aircraft_metadata():
    logger.info("Promoting latest telemetry metadata to aircraft table...")
    
    # Get the latest point for every aircraft
    # This query finds the maximum ID for each ICAO24
    latest_points = db.query(migrate.FlightTelemetry).distinct(
        migrate.FlightTelemetry.icao24
    ).order_by(
        migrate.FlightTelemetry.icao24, 
        desc(migrate.FlightTelemetry.timestamp)
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
        "--AGL", 
        action="store_true", 
        help="Only set AGL altitude"
    )

    args = parser.parse_args()

    if args.AGL:
        backfill_agl()
    else:
        backfill_telemetry()
        backfill_agl()
        label_flight_phases()

        sync_aircraft_metadata()

    detect_regions_of_interest_clustered(type='fire')
    detect_regions_of_interest_clustered(type='water')

    grow_and_level_up_rois(starting_level=1, buffer_km=1.0, type='fire')
    grow_and_level_up_rois(starting_level=2, buffer_km=1.0, type='fire')
    grow_and_level_up_rois(starting_level=3, buffer_km=1.0, type='fire')
    
    grow_and_level_up_rois(starting_level=1, buffer_km=1.0, type='water')
    grow_and_level_up_rois(starting_level=2, buffer_km=1.0, type='water')
    grow_and_level_up_rois(starting_level=3, buffer_km=1.0, type='water')
 