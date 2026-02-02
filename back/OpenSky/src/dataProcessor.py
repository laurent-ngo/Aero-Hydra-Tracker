import os
import time
import json
from json import JSONDecodeError
import requests
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

import migrate

user = os.getenv('DB_USER', 'postgres')
password = os.getenv('DB_PASSWORD', 'postgres')
db_name = os.getenv('DB_NAME', 'aero_hydra')
db_port = os.getenv('DB_PORT', '5432') # Use string first
db_host = os.getenv('DB_HOST', 'localhost')

db_url = f"postgresql://{user}:{password}@{db_host}:{db_port}/{db_name}"

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
        print(f"Processing aircraft: {icao}")
        
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
    print("Backfill complete!")

def get_ground_elevation(lat, lon):
    try:
        # Using the Open-Elevation public API
        url = f"https://api.open-elevation.com/api/v1/lookup?locations={lat},{lon}"
        response = requests.get(url, timeout=5)
        data = response.json()
        # Returns elevation in meters
        return data['results'][0]['elevation']
    except Exception as e:
        print(f"Elevation lookup failed: {e}")
        return 0 # Default to sea level if lookup fails

def backfill_agl():
    # 1. Fetch only records that have baro_altitude but missing AGL
    # We process in batches to be gentle on the API and memory
    points_to_fix = db.query(migrate.FlightTelemetry).filter(
        migrate.FlightTelemetry.baro_altitude != None,
        migrate.FlightTelemetry.altitude_agl_ft == None
    ).limit(500).all() # Processing 500 at a time is safer

    if not points_to_fix:
        print("No pending AGL calculations found.")
        return

    print(f"Calculating AGL for {len(points_to_fix)} points...")

    for p in points_to_fix:
        # 2. Get the ground height from your new method
        ground_m = get_ground_elevation(p.lat, p.lon)
        
        if ground_m is not None:
            # 3. Calculation: MSL - Ground = AGL
            agl_m = p.baro_altitude - ground_m
            p.altitude_agl_ft = round(agl_m * 3.28084, 0)
            
            time.sleep(0.5) 

    db.commit()
    print("Batch AGL backfill complete.")
    
def calculate_distance(lat1, lon1, lat2, lon2):
    """Returns distance in km between two points."""
    R = 6371.0  # Earth radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def label_flight_phases(threshold_ft=950, water_threshold_ft=50, airfield_radius=10.0, airfield_alt_threshold=1500):
    # 1. Load all airfields into memory for fast lookup
    airfields = db.query(migrate.Airfield).all()

    roi_data = db.query(migrate.RegionOfInterest).filter(migrate.RegionOfInterest.level == 3).all()
    level_3_polygons = []
    for r in roi_data:
        try:
            poly = Polygon(json.loads(r.geometry))
            level_3_polygons.append(poly)
        except(JSONDecodeError, TypeError, ValueError) as e:
            print(f"Skipping ROI {r.id} due to invalid geometry: {e}")
            continue
    
    points = db.query(migrate.FlightTelemetry).filter(
        migrate.FlightTelemetry.altitude_agl_ft != None,
        migrate.FlightTelemetry.baro_altitude_ft != None,
        migrate.FlightTelemetry.is_processed == False 
    ).order_by(
        migrate.FlightTelemetry.timestamp,
        desc(migrate.FlightTelemetry.timestamp)
    ).all()

    if not points:
        print("No new points to label.")
        return
    
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

    count_low_pass = 0
    count_over_water = 0 
    count_at_airfield = 0

    # Runs throught every new points
    for p in points:
        found_near_airfield = False

        p.at_airfield = False
        p.is_over_water = False
        p.is_low_pass = False

        p.is_full = is_full_dict[p.icao24] 
        if p.is_full is None:
            p.is_full =  p.icao24 in water_bombers_dict
     
        # 1. Proximity Check (Highest priority)
        for af in airfields:
            dist = calculate_distance(p.lat, p.lon, af.lat, af.lon)
            if dist <= airfield_radius and p.altitude_agl_ft <= airfield_alt_threshold:
                p.at_airfield = True
                p.latest_airfield = af.icao
                
                # Update our cache for this specific airplane
                airfield_dict[p.icao24] = af.icao

                p.is_full = True
                
                count_at_airfield += 1
                found_near_airfield = True
                break

        # 2. Inheritance Logic (If not currently at an airfield)
        if not found_near_airfield:
            # Check if we already found an airfield for this plane in this batch
            if p.icao24 in airfield_dict:
                p.latest_airfield = airfield_dict[p.icao24]
            else:
                p.latest_airfield = None
        
            # 3. Label Phase (Only if NOT at an airfield)
            if (p.baro_altitude_ft - p.altitude_agl_ft) < water_threshold_ft:
                p.is_over_water = True
                count_over_water += 1

            elif p.altitude_agl_ft <= threshold_ft and p.altitude_agl_ft > 10:
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
    print(f"Labeling complete: {count_low_pass} Low Pass, {count_over_water} Over Water, {count_at_airfield} near Airfields.")

def detect_regions_of_interest_clustered(min_samples=5, distance_meters=200, type='fire'):
    # 1. Calculate the cutoff (15 days ago from now)
    cutoff_timestamp = int((datetime.now() - timedelta(days=15)).timestamp())

    # 1. Fetch points
    if type == 'fire':
        points = db.query(migrate.FlightTelemetry).filter(
            migrate.FlightTelemetry.is_low_pass == True,
            migrate.FlightTelemetry.timestamp >= cutoff_timestamp
        ).all()
    elif type == 'water':
        points = db.query(migrate.FlightTelemetry).filter(
            migrate.FlightTelemetry.is_over_water == True,
            migrate.FlightTelemetry.timestamp >= cutoff_timestamp
        ).all()


    if len(points) < min_samples:
        print("Not enough points to cluster.")
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
        print(f"No {type} ROIs found at Level {starting_level} to grow.")
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
    print(f"Success: Level {starting_level} expanded and merged into {len(final_shapes)} Level {new_level} {type} ROIs.")


def sync_aircraft_metadata():
    print("Promoting latest telemetry metadata to aircraft table...")
    
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
    print(f"Sync complete: {sync_count} aircraft updated with their latest status.")

if __name__ == "__main__":
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
 